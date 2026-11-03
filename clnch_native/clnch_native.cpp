#include <shlobj.h>
#include <intshcut.h>
#include <lm.h>

#include <vector>
#include <list>
#include <string>

#if defined(_DEBUG)
#undef _DEBUG
#include "python.h"
#define _DEBUG
#else
#include "python.h"
#endif

#include "frameobject.h"

#include "pythonutil.h"
#include "strutil.h"

#include "clnch_native.h"

// using namespace clnch;

//-----------------------------------------------------------------------------

#define MODULE_NAME "clnch_native"
static PyObject *Error;

//-----------------------------------------------------------------------------

struct FindFileCacheInfo
{
	std::wstring filename;
	long long filesize;
	DWORD attributes;
	SYSTEMTIME system_time;
};

typedef std::list<FindFileCacheInfo> FindFileCacheInfoList;

class FindFileCache
{
public:
	FindFileCache(const std::wstring &_path, bool _ignore_dot, bool _ignore_dotdot, FindFileCacheInfoList &_info_list)
		: path(_path),
		  ignore_dot(_ignore_dot),
		  ignore_dotdot(_ignore_dotdot),
		  info_list(_info_list)
	{
	}

	FindFileCache(const FindFileCache &src)
		: path(src.path),
		  ignore_dot(src.ignore_dot),
		  ignore_dotdot(src.ignore_dotdot),
		  info_list(src.info_list)
	{
	}

	~FindFileCache()
	{
	}

public:
	std::wstring path;
	bool ignore_dot;
	bool ignore_dotdot;
	FindFileCacheInfoList info_list;
};

typedef std::list<FindFileCache> FindFileCacheList;
static FindFileCacheList find_file_cache_list;

static PyObject *_findFile(PyObject *self, PyObject *args, PyObject *kwds)
{
	PyObject *pypath;
	int ignore_dot = true;
	int ignore_dotdot = true;
	int use_cache = false;

	static char *kwlist[] = {
		"path",
		"ignore_dot",
		"ignore_dotdot",
		"use_cache",
		NULL};

	if (!PyArg_ParseTupleAndKeywords(args, kwds, "O|iii", kwlist,
									 &pypath,
									 &ignore_dot,
									 &ignore_dotdot,
									 &use_cache))
	{
		return NULL;
	}

	std::wstring path;
	if (!PythonUtil::PyStringToWideString(pypath, &path))
		return NULL;

	bool found = false;

	if (use_cache)
	{
		// Search the cache.
		FindFileCacheList::iterator i;
		for (i = find_file_cache_list.begin(); i != find_file_cache_list.end(); ++i)
		{
			if (i->path == path && i->ignore_dot == (ignore_dot != 0) && i->ignore_dotdot == (ignore_dotdot != 0))
			{
				break;
			}
		}

		// A matching cache entry was found.
		if (i != find_file_cache_list.end())
		{
			found = true;

			// Move the entry to the front.
			if (i != find_file_cache_list.begin())
			{
				FindFileCache cache = *i;
				find_file_cache_list.erase(i);
				find_file_cache_list.insert(find_file_cache_list.begin(), cache);
			}
		}
	}

	if (!found)
	{
		FindFileCacheInfoList new_info_list;

		HANDLE handle;
		DWORD error = ERROR_SUCCESS;
		WIN32_FIND_DATA data;

		Py_BEGIN_ALLOW_THREADS
			handle = FindFirstFile(path.c_str(), &data);
			if (handle == INVALID_HANDLE_VALUE)
				error = GetLastError();
		Py_END_ALLOW_THREADS

			if (handle != INVALID_HANDLE_VALUE)
		{
			TIME_ZONE_INFORMATION tz;
			GetTimeZoneInformation(&tz);

			while (true)
			{
				bool ignore = false;

				if (ignore_dot && wcscmp(data.cFileName, L".") == 0)
				{
					ignore = true;
				}
				if (ignore_dotdot && wcscmp(data.cFileName, L"..") == 0)
				{
					ignore = true;
				}

				if (!ignore)
				{
					FindFileCacheInfo info;

					info.filename = data.cFileName;
					info.filesize = (((long long)data.nFileSizeHigh) << 32) + data.nFileSizeLow;
					info.attributes = data.dwFileAttributes;

					SYSTEMTIME system_time;
					FileTimeToSystemTime(&data.ftLastWriteTime, &system_time);
					SystemTimeToTzSpecificLocalTime(&tz, &system_time, &info.system_time);

					new_info_list.push_back(info);
				}

				BOOL found;
				Py_BEGIN_ALLOW_THREADS
					found = FindNextFile(handle, &data);
				Py_END_ALLOW_THREADS if (!found) break;
			}

			Py_BEGIN_ALLOW_THREADS
				FindClose(handle);
			Py_END_ALLOW_THREADS
		}
		else if (error == ERROR_FILE_NOT_FOUND)
		{
			// Treat no matching files as an empty result rather than an error.
			SetLastError(0);
		}
		else
		{
			PyErr_SetFromWindowsErr(error);
			return NULL;
		}

		// Insert the new entry at the front of the cache.
		find_file_cache_list.push_front(FindFileCache(path, ignore_dot != 0, ignore_dotdot != 0, new_info_list));

		// Limit the cache to four entries.
		while (find_file_cache_list.size() > 4)
		{
			find_file_cache_list.pop_back();
		}
	}

	// Convert the cached results to a Python list.
	PyObject *pyret = PyList_New(0);
	{
		// Read the results from the first cache entry.
		FindFileCacheInfoList &info_list = find_file_cache_list.begin()->info_list;

		for (FindFileCacheInfoList::iterator i = info_list.begin(); i != info_list.end(); ++i)
		{
			PyObject *pyitem = Py_BuildValue(
				"(uL(iiiiii)i)",
				i->filename.c_str(),
				i->filesize,
				i->system_time.wYear, i->system_time.wMonth, i->system_time.wDay,
				i->system_time.wHour, i->system_time.wMinute, i->system_time.wSecond,
				i->attributes);

			PyList_Append(pyret, pyitem);

			Py_XDECREF(pyitem);
		}
	}

	return pyret;
}

static PyObject *_enumShare(PyObject *self, PyObject *args, PyObject *kwds)
{
	PyObject *pyservername;

	static char *kwlist[] = {
		"servername",
		NULL};

	if (!PyArg_ParseTupleAndKeywords(args, kwds, "O", kwlist,
									 &pyservername))
	{
		return NULL;
	}

	std::wstring servername;
	if (!PythonUtil::PyStringToWideString(pyservername, &servername))
		return NULL;

	PyObject *pyret = PyList_New(0);
	if (!pyret)
		return NULL;

	NET_API_STATUS res;
	PSHARE_INFO_502 BufPtr = NULL, p;
	DWORD er = 0, tr = 0, resume = 0;

	do
	{
		BufPtr = NULL;
		Py_BEGIN_ALLOW_THREADS
			res = NetShareEnum((wchar_t *)servername.c_str(), 502, (LPBYTE *)&BufPtr, MAX_PREFERRED_LENGTH, &er, &tr, &resume);
		Py_END_ALLOW_THREADS

		if (res == ERROR_SUCCESS || res == ERROR_MORE_DATA)
		{
			p = BufPtr;

			for (unsigned int i = 1; i <= er; i++)
			{
				// Append to the list.
				{
					PyObject *pyitem = Py_BuildValue(
						"(uiuiiiuu)",
						p->shi502_netname,
						p->shi502_type,
						p->shi502_remark,
						p->shi502_permissions,
						p->shi502_max_uses,
						p->shi502_current_uses,
						p->shi502_path,
						p->shi502_passwd);

					if (!pyitem || PyList_Append(pyret, pyitem) < 0)
					{
						Py_XDECREF(pyitem);
						NetApiBufferFree(BufPtr);
						Py_DECREF(pyret);
						return NULL;
					}

					Py_DECREF(pyitem);
				}

				p++;
			}

			// Free the allocated buffer.
			NetApiBufferFree(BufPtr);
		}
		else
		{
			if (BufPtr)
				NetApiBufferFree(BufPtr);
			Py_DECREF(pyret);

			PyErr_SetFromWindowsErr(res);
			return NULL;
		}
	} while (res == ERROR_MORE_DATA);

	return pyret;
}

static PyObject *_addConnection(PyObject *self, PyObject *args, PyObject *kwds)
{
	PyObject *pyhwnd;
	PyObject *pyservername;

	static char *kwlist[] = {
		"hwnd",
		"servername",
		NULL};

	if (!PyArg_ParseTupleAndKeywords(args, kwds, "OO", kwlist,
									 &pyhwnd,
									 &pyservername))
	{
		return NULL;
	}

	size_t hwnd_value = PyLong_AsSize_t(pyhwnd);
	if (PyErr_Occurred())
		return NULL;
	HWND hwnd = reinterpret_cast<HWND>(hwnd_value);

	std::wstring servername;
	if (!PythonUtil::PyStringToWideString(pyservername, &servername))
		return NULL;

	NETRESOURCE resource = {0};
	resource.dwType = RESOURCETYPE_ANY;
	resource.lpLocalName = 0;
	resource.lpRemoteName = (wchar_t *)servername.c_str();
	resource.lpProvider = 0;

	DWORD ret = WNetAddConnection3(hwnd, &resource, 0, 0, CONNECT_INTERACTIVE);

	if (ret)
	{
		PyErr_SetFromWindowsErr(ret);
		return NULL;
	}

	Py_INCREF(Py_None);
	return Py_None;
}

static PyObject *_setFileTime(PyObject *self, PyObject *args)
{
	PyObject *pypath;
	int year, month, day, hour, minute, second;

	if (!PyArg_ParseTuple(args, "O(iiiiii)", &pypath, &year, &month, &day, &hour, &minute, &second))
		return NULL;

	std::wstring path;
	if (!PythonUtil::PyStringToWideString(pypath, &path))
		return NULL;

	const int days_in_month[] = {31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31};
	bool leap = year % 4 == 0 && (year % 100 != 0 || year % 400 == 0);
	if (year < 1601 || year > 30827 || month < 1 || month > 12 ||
		day < 1 || day > days_in_month[month - 1] + (month == 2 && leap) ||
		hour < 0 || hour > 23 || minute < 0 || minute > 59 || second < 0 || second > 59)
	{
		PyErr_SetString(PyExc_ValueError, "invalid local date/time (year must be 1601..30827).");
		return NULL;
	}

	SYSTEMTIME system_time = {0};
	system_time.wYear = year;
	system_time.wMonth = month;
	system_time.wDay = day;
	system_time.wHour = hour;
	system_time.wMinute = minute;
	system_time.wSecond = second;

	DWORD attr = INVALID_FILE_ATTRIBUTES;
	HANDLE hFile = INVALID_HANDLE_VALUE;
	DWORD error = ERROR_SUCCESS, close_error = ERROR_SUCCESS, restore_error = ERROR_SUCCESS;
	bool restore_readonly = false, updated = false;
	const char *operation = NULL;

	Py_BEGIN_ALLOW_THREADS
		do
		{
			// Finish date conversion before changing any file state.
			TIME_ZONE_INFORMATION tz;
			SYSTEMTIME system_time_utc;
			FILETIME file_time_utc;
			operation = "GetTimeZoneInformation";
			if (GetTimeZoneInformation(&tz) == TIME_ZONE_ID_INVALID)
			{
				error = GetLastError();
				break;
			}
			operation = "TzSpecificLocalTimeToSystemTime";
			if (!TzSpecificLocalTimeToSystemTime(&tz, &system_time, &system_time_utc))
			{
				error = GetLastError();
				break;
			}
			operation = "SystemTimeToFileTime";
			if (!SystemTimeToFileTime(&system_time_utc, &file_time_utc))
			{
				error = GetLastError();
				break;
			}
			operation = "GetFileAttributesW";
			attr = GetFileAttributes(path.c_str());
			if (attr == INVALID_FILE_ATTRIBUTES)
			{
				error = GetLastError();
				break;
			}
			if (attr & FILE_ATTRIBUTE_READONLY)
			{
				operation = "clearing read-only attributes";
				if (!SetFileAttributes(path.c_str(), attr & ~FILE_ATTRIBUTE_READONLY))
				{
					error = GetLastError();
					break;
				}
				restore_readonly = true;
			}

			operation = "CreateFileW";
			for (int retry = 0; retry < 5; ++retry)
			{
				hFile = CreateFile(path.c_str(), GENERIC_WRITE, 0, NULL, OPEN_EXISTING,
					(attr & FILE_ATTRIBUTE_DIRECTORY) ? FILE_ATTRIBUTE_NORMAL | FILE_FLAG_BACKUP_SEMANTICS : FILE_ATTRIBUTE_NORMAL, NULL);
				error = hFile == INVALID_HANDLE_VALUE ? GetLastError() : ERROR_SUCCESS;
				if (error != ERROR_SHARING_VIOLATION)
					break;
				Sleep(250);
			}
			if (hFile == INVALID_HANDLE_VALUE)
				break;

			operation = "SetFileTime";
			if (!SetFileTime(hFile, NULL, NULL, &file_time_utc))
				error = GetLastError();
			else
				updated = true;
		} while (false);

		// Cleanup continues after failures and never replaces the first error.
		if (hFile != INVALID_HANDLE_VALUE && !CloseHandle(hFile))
			close_error = GetLastError();
		if (restore_readonly && !SetFileAttributes(path.c_str(), attr))
			restore_error = GetLastError();
	Py_END_ALLOW_THREADS

	if (!error && close_error)
	{
		error = close_error;
		operation = "CloseHandle";
	}
	if (!error && restore_error)
	{
		error = restore_error;
		operation = "restoring file attributes";
	}
	if (error)
	{
		PyErr_SetExcFromWindowsErrWithFilenameObject(PyExc_OSError, error, pypath);
		PyObject *exception = PyErr_GetRaisedException();
		PyObject *note = PyObject_CallMethod(exception, "add_note", "s", operation);
		Py_XDECREF(note);
		if (updated)
		{
			note = PyObject_CallMethod(exception, "add_note", "s", "The timestamp was updated before cleanup failed.");
			Py_XDECREF(note);
		}
		if (close_error)
		{
			note = PyObject_CallMethod(exception, "add_note", "s", "CloseHandle failed during cleanup.");
			Py_XDECREF(note);
		}
		if (restore_error)
		{
			note = PyObject_CallMethod(exception, "add_note", "s", "Restoring file attributes failed; read-only may remain cleared.");
			Py_XDECREF(note);
		}
		PyErr_SetRaisedException(exception);
		return NULL;
	}

	Py_INCREF(Py_None);
	return Py_None;
}

static LPCONTEXTMENU3 context_menu_interface3;
static WNDPROC context_menu_oldWndProc;

static LPITEMIDLIST getItemIDList(HWND hwnd, LPSHELLFOLDER pDesktopFolder, const wchar_t *filename)
{
	LPITEMIDLIST pidl = NULL;
	ULONG chEaten = 0;
	ULONG dwAttributes = 0;
	HRESULT ret;

	wchar_t buf[MAX_PATH];
	if (wcslen(filename) >= MAX_PATH)
		return NULL;
	wcscpy_s(buf, MAX_PATH, filename);

	ret = pDesktopFolder->ParseDisplayName(
		hwnd,
		NULL,
		buf,
		&chEaten,
		&pidl,
		&dwAttributes);

	if (FAILED(ret))
	{
		printf("ParseDisplayName failed\n");
		return NULL;
	}

	return pidl;
}

static LRESULT CALLBACK contextMenuWndProc(HWND hwnd, UINT msg, WPARAM wp, LPARAM lp)
{
	PythonUtil::GIL_Ensure gil_ensure;

	switch (msg)
	{
	case WM_MENUCHAR: // only supported by IContextMenu3
		if (context_menu_interface3)
		{
			LRESULT result = 0;
			HRESULT ret = context_menu_interface3->HandleMenuMsg2(msg, wp, lp, &result);
			return result;
		}
		break;

	case WM_DRAWITEM:
	case WM_MEASUREITEM:
		if (wp)
		{
			break; // if wParam != 0 then the message is not menu-related
		}
		// fall through

	case WM_INITMENUPOPUP:
		if (context_menu_interface3)
		{
			HRESULT ret = context_menu_interface3->HandleMenuMsg(msg, wp, lp);
		}
		return (msg == WM_INITMENUPOPUP ? 0 : TRUE); // inform caller that we handled WM_INITPOPUPMENU by ourself

	default:
		break;
	}

	// call original WndProc of window to prevent undefined bevhaviour of window
	return ::CallWindowProc(context_menu_oldWndProc, hwnd, msg, wp, lp);
}

BOOL doContextMenu(HWND hwnd, int x, int y, LPSHELLFOLDER pFolder, LPITEMIDLIST *lpIDLArray, int num)
{
	LPCONTEXTMENU lpcm = NULL;
	HRESULT ret;
	CMINVOKECOMMANDINFO cmi;
	DWORD dwAttribs = 0;
	int idCmd;
	HMENU hMenu;
	BOOL bSuccess = FALSE;

	// Obtain IContextMenu.
	// The second argument is the number of files;
	// the third is the array of file item ID lists.
	ret = pFolder->GetUIObjectOf(
		hwnd,
		num,
		(LPCITEMIDLIST *)lpIDLArray,
		IID_IContextMenu,
		0,
		(LPVOID *)&lpcm);

	if (FAILED(ret) || !lpcm)
	{
		return FALSE;
	}

	ret = lpcm->QueryInterface(IID_IContextMenu3, (void **)&context_menu_interface3);

	if (SUCCEEDED(ret) && context_menu_interface3)
	{
		hMenu = CreatePopupMenu();

		if (hMenu)
		{
			ret = context_menu_interface3->QueryContextMenu(
				hMenu,
				0,
				1,
				10000,
				CMF_NORMAL | CMF_EXPLORE);

			if (SUCCEEDED(ret))
			{
				context_menu_oldWndProc = (WNDPROC)SetWindowLongPtr(hwnd, GWLP_WNDPROC, (LONG_PTR)contextMenuWndProc);

				if (!context_menu_oldWndProc)
				{
					DestroyMenu(hMenu);
					context_menu_interface3->Release();
					context_menu_interface3 = NULL;
					lpcm->Release();
					return FALSE;
				}

				bSuccess = TRUE;
				idCmd = TrackPopupMenu(hMenu,
									   TPM_LEFTALIGN | TPM_RETURNCMD | TPM_RIGHTBUTTON,
									   x,
									   y,
									   0,
									   hwnd,
									   NULL);

				SetWindowLongPtr(hwnd, GWLP_WNDPROC, (LONG_PTR)context_menu_oldWndProc);
				context_menu_oldWndProc = NULL;

				if (idCmd)
				{
					cmi.cbSize = sizeof(CMINVOKECOMMANDINFO);
					cmi.fMask = 0;
					cmi.hwnd = hwnd;
					cmi.lpVerb = (const char *)MAKEINTRESOURCE(idCmd - 1);
					cmi.lpParameters = NULL;
					cmi.lpDirectory = NULL;
					cmi.nShow = SW_SHOWNORMAL;
					cmi.dwHotKey = 0;
					cmi.hIcon = NULL;

					ret = context_menu_interface3->InvokeCommand(&cmi);
					if (!SUCCEEDED(ret))
						bSuccess = FALSE;
				}
			}

			DestroyMenu(hMenu);
		}

		context_menu_interface3->Release();
		context_menu_interface3 = NULL;
	}

	lpcm->Release();

	return bSuccess;
}

static PyObject *_popupContextMenu(PyObject *self, PyObject *args)
{
	PyObject *pyhwnd;
	int x;
	int y;
	PyObject *pystr_directory;
	PyObject *file_list;

	if (!PyArg_ParseTuple(args, "OiiOO", &pyhwnd, &x, &y, &pystr_directory, &file_list))
		return NULL;

	size_t hwnd_value = PyLong_AsSize_t(pyhwnd);
	if (PyErr_Occurred())
		return NULL;
	HWND hwnd = reinterpret_cast<HWND>(hwnd_value);

	std::wstring str_directory;
	if (!PythonUtil::PyStringToWideString(pystr_directory, &str_directory))
	{
		return NULL;
	}

	if (!PyTuple_Check(file_list) && !PyList_Check(file_list))
	{
		PyErr_SetString(PyExc_TypeError, "argument must be a tuple or list.");
		return NULL;
	}

	Py_ssize_t file_num = PySequence_Length(file_list);
	if (file_num < 0)
		return NULL;
	if (file_num > INT_MAX)
	{
		PyErr_SetString(PyExc_OverflowError, "too many context menu items.");
		return NULL;
	}
	std::vector<std::wstring> filenames((size_t)file_num);
	std::vector<LPITEMIDLIST> item_id_list((size_t)file_num, NULL);
	for (Py_ssize_t i = 0; i < file_num; i++)
	{
		PyObject *filename = PySequence_GetItem(file_list, i);
		if (!filename)
			return NULL;
		bool converted = PythonUtil::PyStringToWideString(filename, &filenames[i]);
		Py_DECREF(filename);
		if (!converted)
			return NULL;
	}

	LPMALLOC pMalloc = NULL;
	LPSHELLFOLDER pDesktopFolder = NULL;
	LPITEMIDLIST directory_item_id = NULL;
	LPSHELLFOLDER pFolder = NULL;

	Py_BEGIN_ALLOW_THREADS

		do
	{
		HRESULT ret = SHGetMalloc(&pMalloc);
		if (FAILED(ret) || !pMalloc)
		{
			printf("SHGetMalloc failed\n");
			break;
		}

		ret = SHGetDesktopFolder(&pDesktopFolder);
		if (FAILED(ret) || !pDesktopFolder)
		{
			printf("SHGetDesktopFolder failed\n");
			break;
		}

		if (str_directory.empty())
		{
			// Computer (drive list).
			ret = SHGetSpecialFolderLocation(hwnd, CSIDL_DRIVES, &directory_item_id);
			if (FAILED(ret))
				break;
		}
		else
		{
			directory_item_id = getItemIDList(hwnd, pDesktopFolder, str_directory.c_str());
		}
		if (!directory_item_id)
			break;

		ret = pDesktopFolder->BindToObject(directory_item_id, NULL, IID_IShellFolder, (LPVOID *)&pFolder);
		if (FAILED(ret) || !pFolder)
		{
			printf("BindToObject failed\n");
			break;
		}

		bool parsed = true;
		for (Py_ssize_t i = 0; i < file_num; i++)
		{
			item_id_list[i] = getItemIDList(hwnd, pFolder, filenames[i].c_str());
			if (!item_id_list[i])
			{
				parsed = false;
				break;
			}
		}
		if (parsed)
			doContextMenu(hwnd, x, y, pFolder, item_id_list.data(), (int)file_num);
	} while (false);

	for (Py_ssize_t i = 0; i < file_num; i++)
	{
		if (item_id_list[i])
			pMalloc->Free(item_id_list[i]);
	}
	if (pFolder)
		pFolder->Release();
	if (directory_item_id)
		pMalloc->Free(directory_item_id);
	if (pDesktopFolder)
		pDesktopFolder->Release();
	if (pMalloc)
		pMalloc->Release();

	Py_END_ALLOW_THREADS

	Py_INCREF(Py_None);
	return Py_None;
}

#include "olednd_dataobject.h"
#include "olednd_dropsource.h"

static HDROP CreateHDrop(PyObject *pyfile_list)
{
	HDROP hDrop;

	int file_num = (int)PySequence_Length(pyfile_list);

	std::vector<std::wstring> filename_list;

	size_t total_buffer_size = 0;

	for (int i = 0; i < file_num; i++)
	{
		PyObject *pystr_filename = PySequence_GetItem(pyfile_list, i);
		if (!pystr_filename)
			return NULL;

		std::wstring filename;
		if (!PythonUtil::PyStringToWideString(pystr_filename, &filename))
		{
			Py_DECREF(pystr_filename);
			return NULL;
		}
		filename_list.push_back(filename);

		total_buffer_size += (filename_list[i].length() + 1) * sizeof(wchar_t);

		Py_XDECREF(pystr_filename);

	}

	hDrop = (HDROP)::GlobalAlloc(GHND, sizeof(DROPFILES) + total_buffer_size + 2);
	if (hDrop == NULL)
		return NULL;

	LPDROPFILES lpDropFile;
	lpDropFile = (LPDROPFILES)::GlobalLock(hDrop);
	lpDropFile->pFiles = sizeof(DROPFILES); // Offset to the file-name list.
	lpDropFile->pt.x = 0;
	lpDropFile->pt.y = 0;
	lpDropFile->fNC = FALSE;
	lpDropFile->fWide = TRUE; // TRUE for UTF-16 file names.

	// Copy file names after the structure: filename\0filename\0filename\0\0.
	{
		wchar_t *buf = (wchar_t *)(&lpDropFile[1]);
		size_t remaining_buffer_size_in_word = total_buffer_size / sizeof(wchar_t);

		for (int i = 0; i < file_num; i++)
		{
			wcscpy_s(buf, remaining_buffer_size_in_word, filename_list[i].c_str());
			buf += filename_list[i].length() + 1;
			remaining_buffer_size_in_word -= filename_list[i].length() + 1;
		}
		*buf = 0;
	}

	::GlobalUnlock(hDrop);

	return hDrop;
}

static void CreateMedium(CLIPFORMAT cfFormat, HANDLE hObject, FORMATETC *pFormatetc, STGMEDIUM *pmedium)
{
	pFormatetc->cfFormat = cfFormat;
	pFormatetc->dwAspect = DVASPECT_CONTENT;
	pFormatetc->lindex = -1;
	pFormatetc->ptd = NULL;
	pFormatetc->tymed = TYMED_HGLOBAL;

	pmedium->hGlobal = hObject;
	pmedium->tymed = TYMED_HGLOBAL;
	pmedium->pUnkForRelease = NULL;
}

static PyObject *_doDragAndDrop(PyObject *self, PyObject *args)
{
	PyObject *pyfile_list;

	if (!PyArg_ParseTuple(args, "O", &pyfile_list))
		return NULL;

	if (!PyTuple_Check(pyfile_list) && !PyList_Check(pyfile_list))
	{
		PyErr_SetString(PyExc_TypeError, "argument must be a tuple or list.");
		return NULL;
	}

	{
		CDataObject *dobj = NULL;
		CDropSource *dsrc = NULL;
		HANDLE hObject = NULL;
		FORMATETC fmt;
		STGMEDIUM medium;
		DWORD dwEffect;
		int ret;

		// Create CDataObject and register CF_HDROP data.
		dobj = new CDataObject();
		if (dobj == NULL)
			goto error;
		if (!dobj->allocate(1))
			goto error;

		if ((hObject = CreateHDrop(pyfile_list)) == NULL)
			goto error;
		CreateMedium(CF_HDROP, hObject, &fmt, &medium);
		if (dobj->SetData(&fmt, &medium, TRUE) != S_OK)
			goto error; // On failure, hObject is still freed by the cleanup below.

		hObject = NULL;

		dsrc = new CDropSource();
		if (dsrc == NULL)
			goto error;

		ret = DoDragDrop(dobj, dsrc, DROPEFFECT_COPY, &dwEffect);

	error:

		if (dsrc)
			dsrc->Release();
		if (dobj)
			dobj->Release();
		if (hObject)
			GlobalFree(hObject);
	}

	if (PyErr_Occurred())
		return NULL;

	Py_INCREF(Py_None);
	return Py_None;
}

static PyObject *_getShellLinkInfo(PyObject *self, PyObject *args)
{
	PyObject *pylnk;

	if (!PyArg_ParseTuple(args, "O", &pylnk))
		return NULL;

	std::wstring lnk;
	if (!PythonUtil::PyStringToWideString(pylnk, &lnk))
		return NULL;

	HRESULT hres = CoInitialize(NULL);
	IShellLink *psl = NULL;
	WIN32_FIND_DATA wfd;

	TCHAR file[MAX_PATH] = {0};
	TCHAR param[MAX_PATH] = {0};
	TCHAR directory[MAX_PATH] = {0};
	int swmode = SW_SHOWNORMAL;

	if (SUCCEEDED(hres))
	{
		// Create an IShellLink object and obtain its interface pointer.
		hres = CoCreateInstance(CLSID_ShellLink, NULL, CLSCTX_INPROC_SERVER,
								IID_IShellLink, (void **)&psl);
		if (SUCCEEDED(hres) && psl)
		{
			IPersistFile *ppf = NULL;

			// Query the IPersistFile interface.
			hres = psl->QueryInterface(IID_IPersistFile, (void **)&ppf);
			if (SUCCEEDED(hres) && ppf)
			{
				// Load the shortcut.
				hres = ppf->Load(lnk.c_str(), STGM_READ);

				if (SUCCEEDED(hres))
				{
					// Retrieve the link target and launch parameters.
					hres = psl->GetPath(file, MAX_PATH, &wfd, SLGP_UNCPRIORITY);
					if (SUCCEEDED(hres))
						hres = psl->GetArguments(param, MAX_PATH);
					if (SUCCEEDED(hres))
						hres = psl->GetWorkingDirectory(directory, MAX_PATH);
					if (SUCCEEDED(hres))
						hres = psl->GetShowCmd(&swmode);
				}

				// Release the IPersistFile pointer.
				ppf->Release();
			}
			else if (SUCCEEDED(hres))
				hres = E_NOINTERFACE;
			// Release the IShellLink pointer.
			psl->Release();
		}
		else if (SUCCEEDED(hres))
			hres = E_NOINTERFACE;

		CoUninitialize();
	}

	if (SUCCEEDED(hres))
	{
		PyObject *pyret = Py_BuildValue("uuui", file, param, directory, swmode);
		return pyret;
	}
	else
	{
		PyErr_SetString(PyExc_WindowsError, "can't access to shortcut info.");
		return NULL;
	}
}

static PyObject *_getInternetShortcutInfo(PyObject *self, PyObject *args)
{
	PyObject *pylnk;

	if (!PyArg_ParseTuple(args, "O", &pylnk))
		return NULL;

	std::wstring lnk;
	if (!PythonUtil::PyStringToWideString(pylnk, &lnk))
		return NULL;

	HRESULT hres = CoInitialize(NULL);
	IUniformResourceLocator *psl = NULL;

	PyObject *pyurl = NULL;

	if (SUCCEEDED(hres))
	{
		// Create an IUniformResourceLocator object and obtain its interface pointer.
		hres = CoCreateInstance(CLSID_InternetShortcut, NULL, CLSCTX_INPROC_SERVER,
								IID_IUniformResourceLocator, (void **)&psl);
		if (SUCCEEDED(hres) && psl)
		{
			IPersistFile *ppf = NULL;

			// Query the IPersistFile interface.
			hres = psl->QueryInterface(IID_IPersistFile, (void **)&ppf);
			if (SUCCEEDED(hres) && ppf)
			{
				// Load the shortcut.
				hres = ppf->Load(lnk.c_str(), STGM_READ);

				if (SUCCEEDED(hres))
				{
					// Retrieve the target URL.
					wchar_t *p = NULL;
					hres = psl->GetURL(&p);
					if (SUCCEEDED(hres) && p)
					{
						pyurl = PyUnicode_FromWideChar(p, -1);
					}
					else if (SUCCEEDED(hres))
						pyurl = PyUnicode_FromString("");
					CoTaskMemFree(p);
				}

				// Release the IPersistFile pointer.
				ppf->Release();
			}
			else if (SUCCEEDED(hres))
				hres = E_NOINTERFACE;
			// Release the IUniformResourceLocator pointer.
			psl->Release();
		}
		else if (SUCCEEDED(hres))
			hres = E_NOINTERFACE;

		CoUninitialize();
	}

	if (SUCCEEDED(hres))
	{
		return pyurl;
	}
	else
	{
		PyErr_SetString(PyExc_WindowsError, "can't access to internet shortcut info.");
		return NULL;
	}
}

static PyObject *_chooseColor(PyObject *self, PyObject *args)
{
	PyObject *pyhwnd;
	PyObject *py_initial_color = NULL;
	PyObject *py_color_table = NULL;

	if (!PyArg_ParseTuple(args, "OOO", &pyhwnd, &py_initial_color, &py_color_table))
		return NULL;

	size_t hwnd_value = PyLong_AsSize_t(pyhwnd);
	if (PyErr_Occurred())
		return NULL;
	HWND hwnd = reinterpret_cast<HWND>(hwnd_value);

	COLORREF initial_color = 0;
	if (py_initial_color != Py_None)
	{
		if (!PyTuple_Check(py_initial_color))
		{
			PyErr_SetString(PyExc_TypeError, "initial_color must be an RGB tuple or None");
			return NULL;
		}
		int r, g, b;
		if (!PyArg_ParseTuple(py_initial_color, "iii", &r, &g, &b))
			return NULL;

		initial_color = RGB(r, g, b);
	}

	COLORREF color_table[16] = {0};
	if (py_color_table != Py_None)
	{
		if (!PySequence_Check(py_color_table))
		{
			PyErr_SetString(PyExc_TypeError, "color_table must be a sequence or None");
			return NULL;
		}
		Py_ssize_t item_num = PySequence_Length(py_color_table);
		if (item_num < 0)
			return NULL;
		for (int i = 0; i < item_num && i < 16; i++)
		{
			PyObject *item = PySequence_GetItem(py_color_table, i);
			if (!item)
				return NULL;

			if (!PyTuple_Check(item))
			{
				PyErr_SetString(PyExc_TypeError, "color_table entries must be RGB tuples");
				Py_DECREF(item);
				return NULL;
			}
			int r, g, b;
			if (!PyArg_ParseTuple(item, "iii", &r, &g, &b))
			{
				Py_DECREF(item);
				return NULL;
			}

			color_table[i] = RGB(r, g, b);
			Py_DECREF(item);
		}
	}

	CHOOSECOLOR cc = {0};

	cc.lStructSize = sizeof(CHOOSECOLOR);
	cc.hwndOwner = hwnd;
	cc.rgbResult = initial_color;
	cc.lpCustColors = color_table;
	cc.Flags = CC_FULLOPEN | CC_RGBINIT;

	BOOL result = ChooseColor(&cc);

	int color_table_rgb[16][3];
	for (int i = 0; i < 16; i++)
	{
		color_table_rgb[i][0] = GetRValue(cc.lpCustColors[i]);
		color_table_rgb[i][1] = GetGValue(cc.lpCustColors[i]);
		color_table_rgb[i][2] = GetBValue(cc.lpCustColors[i]);
	}

	PyObject *pyret = Py_BuildValue("i(iii)((iii),(iii),(iii),(iii),(iii),(iii),(iii),(iii),(iii),(iii),(iii),(iii),(iii),(iii),(iii),(iii))",
									result,
									GetRValue(cc.rgbResult), GetGValue(cc.rgbResult), GetBValue(cc.rgbResult),
									color_table_rgb[0][0], color_table_rgb[0][1], color_table_rgb[0][2],
									color_table_rgb[1][0], color_table_rgb[1][1], color_table_rgb[1][2],
									color_table_rgb[2][0], color_table_rgb[2][1], color_table_rgb[2][2],
									color_table_rgb[3][0], color_table_rgb[3][1], color_table_rgb[3][2],
									color_table_rgb[4][0], color_table_rgb[4][1], color_table_rgb[4][2],
									color_table_rgb[5][0], color_table_rgb[5][1], color_table_rgb[5][2],
									color_table_rgb[6][0], color_table_rgb[6][1], color_table_rgb[6][2],
									color_table_rgb[7][0], color_table_rgb[7][1], color_table_rgb[7][2],
									color_table_rgb[8][0], color_table_rgb[8][1], color_table_rgb[8][2],
									color_table_rgb[9][0], color_table_rgb[9][1], color_table_rgb[9][2],
									color_table_rgb[10][0], color_table_rgb[10][1], color_table_rgb[10][2],
									color_table_rgb[11][0], color_table_rgb[11][1], color_table_rgb[11][2],
									color_table_rgb[12][0], color_table_rgb[12][1], color_table_rgb[12][2],
									color_table_rgb[13][0], color_table_rgb[13][1], color_table_rgb[13][2],
									color_table_rgb[14][0], color_table_rgb[14][1], color_table_rgb[14][2],
									color_table_rgb[15][0], color_table_rgb[15][1], color_table_rgb[15][2]);
	return pyret;
}

/**
@cond japanese
@page clnch_native_api clnch_native API

import clnch_nativeで使うWindowsのファイル・共有・Shell操作です。表では位置引数を示し、
findFile・enumShare・addConnectionだけは記載した引数名のキーワードも使えます。
パス・名前はstr、整数はC int（HWNDだけは符号なしポインタ幅）、RGBは3整数tuple（通常0～255）です。
文字列にNULを含めないでください。埋め込みNULはValueErrorです。Errorは公開された例外型ですが、下表のOS失敗は主にOSErrorです。
各操作は呼出しスレッドで同期実行します。Shell・色選択・接続UIはUIスレッドから使い、
長いファイル/共有列挙は@ref threadutil またはMainWindow.subThreadCallを使ってください。
import時には呼出しスレッドでCOM/OLEを初期化します。他スレッドのCOM初期化を代行しません。
完成例は@ref extensions を参照してください。

## ファイルとネットワーク

| Python署名 | 戻り値・副作用・失敗 |
|---|---|
| clnch_native.findFile(path, ignore_dot=True, ignore_dotdot=True, use_cache=False) | Windowsワイルドカードを含むパスを列挙し、list[(name, size, time, attributes)]を返す。nameは基底名、sizeはバイト数、timeはローカル最終更新日時の(year, month, day, hour, minute, second)、attributesはFILE_ATTRIBUTE_*のビット値。並べ替えない。ignore_dot/ignore_dotdotは.と..だけを除外する整数フラグ。該当ファイルなしは[]、開始時の他のOS失敗はOSError。FindNextFile途中の失敗と正常終端は区別しない |
| clnch_native.enumShare(servername) | servernameはstrのUNCサーバー名（例: `r"\\server"`）。空文字列はローカルコンピューターを指定します。非strはTypeError、文字列変換失敗は元の例外を送出し、列挙は開始しません。SHARE_INFO_502のlist[(netname, type, remark, permissions, max_uses, current_uses, path, passwd)]。文字列/整数はWindowsの値で、NULLの文字列フィールドはNone。typeはディスク共有だけとは限らない。列挙権限・ネットワーク失敗はOSError。接続もドライブ割当もしない |
| clnch_native.addConnection(hwnd, servername) | HWNDを所有者としてUNC名へWNetAddConnection3の対話接続を行いNone。ドライブ文字は割り当てない。認証UIを出し得る。取消もOS失敗もOSError。成功はその時点の接続であり、将来の利用可能性は保証しない |
| clnch_native.setFileTime(path, time) | timeはローカル日時の6整数tuple（年1601～30827、実在する月日、時0～23、分/秒0～59）。既存ファイル/ディレクトリの最終更新日時だけを変更し、更新と後始末の成功時はNone。無効な日時はファイル変更前にValueError。日時変換・属性取得/変更・open・更新・close・属性復元のOS失敗はwinerrorとfilenameを持つOSError。読取専用属性を一時解除し、失敗時もハンドル解放と属性復元を試み、最初のエラーを保持する。更新後の後始末失敗や属性復元失敗は例外のnotesへ記録する（時刻のロールバックはしない）。共有違反のopenは最大5回試行（各250ms待機） |

findFileは常に結果を4件までのプロセス内キャッシュへ追加します。use_cache=Trueはパス文字列と
2つの除外フラグが一致した結果を再利用し、経過時間による失効はありません。Falseは実際に列挙し直します。
時刻変更や外部更新後に新しい情報が必要ならFalseを使います。返却list/tupleは独立したPython値です。
列挙中のファイル変更に対する一貫したスナップショットは提供しません。

## Shellと色選択

| Python署名 | 戻り値・副作用・失敗 |
|---|---|
| clnch_native.getShellLinkInfo(path) | .lnkを読み、(target, arguments, working_directory, show_command)を返す。最初の3つはstr、最後はWin32のSW_*整数。起動・リンク先存在確認は行わない。各文字列はMAX_PATH長のバッファを使い、失敗はOSError |
| clnch_native.getInternetShortcutInfo(path) | .urlからURLのstrを返す。URL未設定は空文字列になり得る。開いたり取得先へ通信したりしない。COM/読込み失敗はOSError |
| clnch_native.popupContextMenu(hwnd, x, y, directory, filenames) | 画面ピクセル(x, y)にShellメニューを同期表示し、選択操作を実行する。filenamesはdirectory内の相対名のlist/tuple。空directoryはComputer（ドライブ一覧）。取消・内部Shell失敗・実行後のいずれもNoneで、成否を判別できない。引数不正はTypeError/OverflowError。パス解析はMAX_PATH未満。同時/入れ子に呼ばない |
| clnch_native.doDragAndDrop(filenames) | 絶対パスstrのlist/tupleからCF_HDROPを作り、COPYだけのOLEドラッグを同期実行。完了・取消・一部の準備失敗はNoneで、受け手のコピー成否は返さない。型/文字列変換失敗は例外。生成したデータとCOM資源は内部で解放する |
| clnch_native.chooseColor(hwnd, initial_color, color_table) | モーダル色選択。戻り値は(result, rgb, table)：resultは確定時の非ゼロ整数、取消/ダイアログ失敗時0、rgbは3整数tuple、tableは16個のRGB tupleのtuple。initial_color=Noneは黒。color_table=Noneは黒16色、sequenceなら先頭16色だけ使い残りは黒。initial_colorと各色は3整数tuple（list不可）。型・要素数の不正はTypeError、C int範囲外はOverflowErrorで、ダイアログを開かない。成分は`__index__`による整数変換を受け付け、0～255への範囲検査・丸めはせず従来どおり下位8bitを使う。sequenceの長さ・要素取得の例外は伝播する。17色目以降は取得・検証しない。入力tableは変更しない。result=0ならrgbを確定色として適用しない |

Shellメニュー・ドラッグの選択操作はファイル等を変更し得ます。これらのNoneは「実行成功」を表しません。
hwndはwindow.getHWND()等から得た有効な所有者ハンドルを使います。負数/ポインタ幅超過はOverflowErrorです。
色ダイアログは呼出し中にメッセージを処理するため再入を考慮してください。
通常の起動にはMainWindow.ShellExecuteCommand、フォームには@ref widget を先に検討できます。
@endcond
*/

/**
@cond english
@page clnch_native_api clnch_native APIs

import clnch_native provides Windows file, share and Shell operations. Tables show positional arguments;
only findFile, enumShare and addConnection also accept the displayed keyword names.
Paths/names are str, integers fit C int (except unsigned pointer-width HWND), and RGB values are tuples of three integers (normally 0..255).
Exclude NUL from strings; embedded NUL raises ValueError. Error is an exported exception type; OS failures below primarily raise OSError.
Operations run synchronously on the calling thread. Use the UI thread for Shell, color and connection dialogs;
use @ref threadutil or MainWindow.subThreadCall for slow file/share enumeration.
Import initializes COM/OLE on the importing thread, not on other threads.
See @ref extensions for a complete example.

## Files and networks

| Python signature | Result, effects and failures |
|---|---|
| clnch_native.findFile(path, ignore_dot=True, ignore_dotdot=True, use_cache=False) | Enumerate a Windows wildcard path into list[(name, size, time, attributes)]. name is the base name, size is bytes, time is local last-write (year, month, day, hour, minute, second), and attributes is a FILE_ATTRIBUTE_* bit mask. No sorting. Integer ignore_dot/ignore_dotdot flags exclude only `.` and `..`. No matches returns []; other initial OS failures raise OSError. Mid-enumeration FindNextFile failures are not distinguished from normal completion |
| clnch_native.enumShare(servername) | servername is a str UNC server name, e.g. `r"\\server"`. An empty string selects the local computer. Non-str input raises TypeError; string conversion failures propagate the original exception without starting enumeration. Return SHARE_INFO_502 as list[(netname, type, remark, permissions, max_uses, current_uses, path, passwd)]. Strings/integers retain Windows values; NULL string fields become None. type is not limited to disk shares. Permission/network failures raise OSError. Does not connect or map a drive |
| clnch_native.addConnection(hwnd, servername) | Make an interactive WNetAddConnection3 connection to the UNC name, owned by HWND; return None. Does not assign a drive letter. May show authentication UI. Cancellation and OS failures raise OSError. Success does not guarantee future availability |
| clnch_native.setFileTime(path, time) | time is a tuple of six local date/time integers (year 1601..30827, a valid calendar date, hour 0..23, minute/second 0..59). Change only the last-write time of an existing file/directory; return None after both update and cleanup succeed. Invalid dates raise ValueError before file changes. OS failures in conversion, attribute lookup/change, open, update, close or restoration raise OSError with winerror and filename. Temporarily clear read-only; attempt handle release and attribute restoration even after failure, retaining the first error. Exception notes identify cleanup failure after an update and attribute restoration failure; the timestamp is not rolled back. Retry sharing-violation opens at most five times with 250ms waits |

findFile always inserts results into a process-local cache of at most four entries. use_cache=True reuses
an entry with the exact path string and exclusion flags; there is no time-based expiry. False enumerates again.
Use False for fresh information after timestamp or external changes. Returned lists/tuples are independent Python values.
Enumeration does not provide a consistent snapshot against concurrent file changes.

## Shell and color selection

| Python signature | Result, effects and failures |
|---|---|
| clnch_native.getShellLinkInfo(path) | Read .lnk into (target, arguments, working_directory, show_command): three strings and a Win32 SW_* integer. Does not launch or check target existence. Strings use MAX_PATH-sized buffers. Failures raise OSError |
| clnch_native.getInternetShortcutInfo(path) | Return the URL str from .url, possibly empty when unset. Does not open it or contact the destination. COM/read failures raise OSError |
| clnch_native.popupContextMenu(hwnd, x, y, directory, filenames) | Synchronously show a Shell menu at screen-pixel (x, y) and invoke the selection. filenames is a list/tuple of names relative to directory. Empty directory means Computer (drives). Cancellation, internal Shell failures and completed invocation all return None without a success indicator. Invalid arguments raise TypeError/OverflowError. Path parsing requires fewer than MAX_PATH characters. Do not call concurrently or recursively |
| clnch_native.doDragAndDrop(filenames) | Build CF_HDROP from a list/tuple of absolute path strings and run a synchronous COPY-only OLE drag. Completion, cancellation and some preparation failures return None; destination copy success is not returned. Type/string conversion failures raise exceptions. Internally release created data and COM resources |
| clnch_native.chooseColor(hwnd, initial_color, color_table) | Modal color selection returns (result, rgb, table): result is a nonzero integer on acceptance, 0 on cancel/dialog failure; rgb is a three-integer tuple; table is a tuple of 16 RGB tuples. initial_color=None means black. color_table=None means 16 black colors; a sequence supplies at most its first 16 colors, with missing entries black. initial_color and each color must be three-integer tuples (not lists). Invalid types or lengths raise TypeError; values outside C int raise OverflowError, before opening the dialog. Components accept integer conversion via `__index__`; retain the low 8 bits without checking or clamping to 0..255. Sequence length/item exceptions propagate. Entries after the first 16 are neither fetched nor validated. Does not mutate the input table. Do not apply rgb as an accepted color when result=0 |

Shell menu and drag selections can change files and other state. None does not mean successful execution.
Use a valid owner HWND such as window.getHWND(); negative or oversized handles raise OverflowError.
Color dialogs dispatch messages while running, so consider reentrancy.
Prefer MainWindow.ShellExecuteCommand for ordinary launching and @ref widget for forms.
@endcond
*/

static PyMethodDef clnch_native_funcs[] =
	{
		{"findFile", (PyCFunction)_findFile, METH_VARARGS | METH_KEYWORDS, ""},
		{"enumShare", (PyCFunction)_enumShare, METH_VARARGS | METH_KEYWORDS, ""},
		{"addConnection", (PyCFunction)_addConnection, METH_VARARGS | METH_KEYWORDS, ""},
		{"setFileTime", (PyCFunction)_setFileTime, METH_VARARGS, ""},
		{"popupContextMenu", _popupContextMenu, METH_VARARGS, ""},
		{"doDragAndDrop", _doDragAndDrop, METH_VARARGS, ""},
		{"getShellLinkInfo", _getShellLinkInfo, METH_VARARGS, ""},
		{"getInternetShortcutInfo", _getInternetShortcutInfo, METH_VARARGS, ""},
		{"chooseColor", _chooseColor, METH_VARARGS, ""},
		{NULL, NULL, 0, NULL}};

// ----------------------------------------------------------------------------

static PyModuleDef clnch_native_module =
	{
		PyModuleDef_HEAD_INIT,
		MODULE_NAME,
		"clnch_native module.",
		-1,
		clnch_native_funcs,
		NULL, NULL, NULL, NULL};

PyMODINIT_FUNC PyInit_clnch_native(void)
{
	CoInitialize(NULL);
	OleInitialize(NULL);

	PyObject *m, *d;

	m = PyModule_Create(&clnch_native_module);
	if (m == NULL)
		return NULL;

	d = PyModule_GetDict(m);

	Error = PyErr_NewException(MODULE_NAME ".Error", NULL, NULL);
	PyDict_SetItemString(d, "Error", Error);

	if (PyErr_Occurred())
	{
		Py_FatalError("can't initialize module " MODULE_NAME);
	}

	return m;
}
