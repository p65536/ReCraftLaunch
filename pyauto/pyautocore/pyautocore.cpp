#include <string>
#include <vector>
#include <list>

#include <windows.h>
#include <tchar.h>
#include <tlhelp32.h>
#include <UIAutomation.h>
#include <new>
#include <limits.h>
#include <wrl/client.h>

#if defined(_DEBUG)
#undef _DEBUG
#include "python.h"
#define _DEBUG
#else
#include "python.h"
#endif

#include "kbhook.h"
#include "mousehook.h"
#include "clipboard.h"
#include "pythonutil.h"
#include "pyautocore.h"

using namespace std;

// ------------ const -----------------------------------
#define MODULE_NAME "pyautocore"
#define PYAUTO_WINDOW_NAME "pyauto"

// ------------ globals -----------------------------------

namespace pyauto
{
	Globals g;
};

using namespace pyauto;

// ------------ stringutil -----------------------------------

namespace pyauto
{
	typedef wstring _tString;

	namespace stringutil
	{
		static bool PyStringTo_tString(PyObject *pystr, _tString *str)
		{
			if (PyUnicode_Check(pystr))
			{
				wchar_t *s = PyUnicode_AsWideCharString(pystr, NULL);
				if (!s)
					return false;

				*str = s;
				PyMem_Free(s);
				return true;
			}
			else
			{
				*str = _T("");
				return false;
			}
		}

	}; // namespace stringutil
}; // namespace pyauto

// ------------ PyObject_Window -----------------------------------------

namespace pyauto
{
	// Non-owning index; Window_dealloc removes each wrapper before freeing it.
	static list<PyObject *> window_list;

	static PyObject *WindowObject_FromHWND(HWND hwnd)
	{
		if (!hwnd)
		{
			Py_INCREF(Py_None);
			return Py_None;
		}

		list<PyObject *>::iterator i;
		for (i = window_list.begin(); i != window_list.end(); i++)
		{
			if (((PyObject_Window *)(*i))->hwnd == hwnd)
			{
				Py_INCREF(*i);
				return (*i);
			}
		}

		PyObject_Window *pywnd;
		pywnd = PyObject_New(PyObject_Window, &PyType_Window);
		if (!pywnd)
			return NULL;
		pywnd->hwnd = hwnd;

		try
		{
			window_list.push_back((PyObject *)pywnd);
		}
		catch (const std::bad_alloc &)
		{
			Py_DECREF(pywnd);
			return PyErr_NoMemory();
		}

		return (PyObject *)pywnd;
	}

	static void WindowObject_Remove(PyObject *obj)
	{
		list<PyObject *>::iterator i;
		for (i = window_list.begin(); i != window_list.end(); i++)
		{
			if ((*i) == obj)
			{
				window_list.erase(i);
				return;
			}
		}
	}
}; // namespace pyauto

static void Window_dealloc(PyObject *self)
{
	WindowObject_Remove(self);
	self->ob_type->tp_free(self);
}

static PyObject *Window_getText(PyObject *self, PyObject *args)
{
	if (!PyArg_ParseTuple(args, ""))
		return NULL;

	HWND hwnd = ((PyObject_Window *)self)->hwnd;
	if (!hwnd)
	{
		PyErr_SetString(PyExc_ValueError, "invalid window object.");
		return NULL;
	}

	int len = ::GetWindowTextLength(hwnd);

	TCHAR *buf = new TCHAR[len + 2];
	::GetWindowText(hwnd, buf, len + 2);

	PyObject *pyret = Py_BuildValue("u", buf);

	delete[] buf;

	return pyret;
}

static PyObject *Window_getClassName(PyObject *self, PyObject *args)
{
	if (!PyArg_ParseTuple(args, ""))
		return NULL;

	HWND hwnd = ((PyObject_Window *)self)->hwnd;
	if (!hwnd)
	{
		PyErr_SetString(PyExc_ValueError, "invalid window object.");
		return NULL;
	}

	TCHAR buf[256];
	int length = ::GetClassName(hwnd, buf, _countof(buf));

	PyObject *pyret = PyUnicode_FromWideChar(buf, length);

	return pyret;
}

static bool _Window_getProcessInfoFromHWND(HWND hwnd, TCHAR *process_name, TCHAR *process_path)
{
// Undocumented flag to omit heap information from the process snapshot.
#define TH32CS_SNAPNOHEAPS (0x40000000)

	DWORD pid = 0;
	GetWindowThreadProcessId(hwnd, &pid);

	bool ret = false;
	HANDLE process_snapshot = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS | TH32CS_SNAPNOHEAPS, 0);
	if (process_snapshot != INVALID_HANDLE_VALUE)
	{
		PROCESSENTRY32 process_entry;
		process_entry.dwSize = sizeof(PROCESSENTRY32);
		if (Process32First(process_snapshot, &process_entry))
		{
			while (true)
			{
				if (process_entry.th32ProcessID == pid)
				{
					if (process_name)
					{
						lstrcpy(process_name, process_entry.szExeFile);
						ret = true;
					}

					if (process_path)
					{
						HANDLE module_handle = CreateToolhelp32Snapshot(TH32CS_SNAPMODULE | TH32CS_SNAPNOHEAPS, process_entry.th32ProcessID);
						if (module_handle == INVALID_HANDLE_VALUE)
						{
							PyErr_Format(PyExc_WindowsError, "CreateToolhelp32Snapshot failed : lineno=%d errno=%d", __LINE__, GetLastError());
							break;
						}

						MODULEENTRY32 module_entry;
						module_entry.dwSize = sizeof(MODULEENTRY32);
						if (Module32First(module_handle, &module_entry))
						{
							lstrcpy(process_path, module_entry.szExePath);
							ret = true;
						}
						else
						{
							PyErr_Format(PyExc_WindowsError, "Module32First failed : lineno=%d errno=%d", __LINE__, GetLastError());
						}

						CloseHandle(module_handle);
					}

					break;
				}

				if (!Process32Next(process_snapshot, &process_entry))
				{
					if (GetLastError() == ERROR_NO_MORE_FILES)
					{
						if (process_name)
						{
							lstrcpy(process_name, L"");
						}
						if (process_path)
						{
							lstrcpy(process_path, L"");
						}
						ret = true;
						break;
					}

					PyErr_Format(PyExc_WindowsError, "Process32Next failed : lineno=%d errno=%d", __LINE__, GetLastError());
					break;
				}
			}
		}
		else
		{
			PyErr_Format(PyExc_WindowsError, "Process32First failed : lineno=%d errno=%d", __LINE__, GetLastError());
		}

		CloseHandle(process_snapshot);
	}
	else
	{
		PyErr_Format(PyExc_WindowsError, "CreateToolhelp32Snapshot failed : lineno=%d errno=%d", __LINE__, GetLastError());
	}

	return ret;
}

static PyObject *Window_getProcessName(PyObject *self, PyObject *args)
{
	if (!PyArg_ParseTuple(args, ""))
		return NULL;

	HWND hwnd = ((PyObject_Window *)self)->hwnd;
	if (!hwnd)
	{
		PyErr_SetString(PyExc_ValueError, "invalid window object.");
		return NULL;
	}

	TCHAR buf[MAX_PATH];
	bool ret = _Window_getProcessInfoFromHWND(hwnd, buf, NULL);
	if (!ret)
	{
		// _Window_getProcessInfoFromHWND sets the error.

		return NULL;
	}

	PyObject *pyret = Py_BuildValue("u", buf);

	return pyret;
}

static PyObject *Window_getProcessPath(PyObject *self, PyObject *args)
{
	if (!PyArg_ParseTuple(args, ""))
		return NULL;

	HWND hwnd = ((PyObject_Window *)self)->hwnd;
	if (!hwnd)
	{
		PyErr_SetString(PyExc_ValueError, "invalid window object.");
		return NULL;
	}

	TCHAR buf[MAX_PATH];
	bool ret = _Window_getProcessInfoFromHWND(hwnd, NULL, buf);
	if (!ret)
	{
		// _Window_getProcessInfoFromHWND sets the error.

		return NULL;
	}

	PyObject *pyret = Py_BuildValue("u", buf);

	return pyret;
}

static PyObject *Window_getHWND(PyObject *self, PyObject *args)
{
	if (!PyArg_ParseTuple(args, ""))
		return NULL;

	HWND hwnd = ((PyObject_Window *)self)->hwnd;
	if (!hwnd)
	{
		PyErr_SetString(PyExc_ValueError, "invalid window object.");
		return NULL;
	}

	PyObject *pyret = PyLong_FromVoidPtr(hwnd);
	return pyret;
}

static PyObject *Window_getRect(PyObject *self, PyObject *args)
{
	if (!PyArg_ParseTuple(args, ""))
		return NULL;

	HWND hwnd = ((PyObject_Window *)self)->hwnd;
	if (!hwnd)
	{
		PyErr_SetString(PyExc_ValueError, "invalid window object.");
		return NULL;
	}

	RECT rect;
	::GetWindowRect(hwnd, &rect);

	PyObject *pyret = Py_BuildValue("(iiii)", rect.left, rect.top, rect.right, rect.bottom);
	return pyret;
}

static PyObject *Window_setRect(PyObject *self, PyObject *args)
{
	RECT rect;

	if (!PyArg_ParseTuple(args, "(iiii)", &rect.left, &rect.top, &rect.right, &rect.bottom))
		return NULL;

	HWND hwnd = ((PyObject_Window *)self)->hwnd;
	if (!hwnd)
	{
		PyErr_SetString(PyExc_ValueError, "invalid window object.");
		return NULL;
	}

	if (::MoveWindow(hwnd, rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top, true))
	{
		Py_INCREF(Py_None);
		return Py_None;
	}
	else
	{
		PyErr_SetFromWindowsErr(0);
		return NULL;
	}
}

static PyObject *Window_getClientRect(PyObject *self, PyObject *args)
{
	if (!PyArg_ParseTuple(args, ""))
		return NULL;

	HWND hwnd = ((PyObject_Window *)self)->hwnd;
	if (!hwnd)
	{
		PyErr_SetString(PyExc_ValueError, "invalid window object.");
		return NULL;
	}

	RECT rect;
	::GetClientRect(hwnd, &rect);

	PyObject *pyret = Py_BuildValue("(iiii)", rect.left, rect.top, rect.right, rect.bottom);
	return pyret;
}

static PyObject *Window_clientToScreen(PyObject *self, PyObject *args)
{
	int x;
	int y;

	if (!PyArg_ParseTuple(args, "ii", &x, &y))
		return NULL;

	HWND hwnd = ((PyObject_Window *)self)->hwnd;
	if (!hwnd)
	{
		PyErr_SetString(PyExc_ValueError, "invalid window object.");
		return NULL;
	}

	POINT point;
	point.x = x;
	point.y = y;

	ClientToScreen(hwnd, &point);

	PyObject *pyret = Py_BuildValue("(ii)", point.x, point.y);
	return pyret;
}

static PyObject *Window_getFirstChild(PyObject *self, PyObject *args)
{
	if (!PyArg_ParseTuple(args, ""))
		return NULL;

	HWND hwnd = ((PyObject_Window *)self)->hwnd;
	if (!hwnd)
	{
		PyErr_SetString(PyExc_ValueError, "invalid window object.");
		return NULL;
	}

	hwnd = ::GetWindow(hwnd, GW_CHILD);
	return WindowObject_FromHWND(hwnd);
}

static PyObject *Window_getLastChild(PyObject *self, PyObject *args)
{
	if (!PyArg_ParseTuple(args, ""))
		return NULL;

	HWND hwnd = ((PyObject_Window *)self)->hwnd;
	if (!hwnd)
	{
		PyErr_SetString(PyExc_ValueError, "invalid window object.");
		return NULL;
	}

	hwnd = ::GetWindow(hwnd, GW_CHILD);
	hwnd = ::GetWindow(hwnd, GW_HWNDLAST);
	return WindowObject_FromHWND(hwnd);
}

static PyObject *Window_getPrevious(PyObject *self, PyObject *args)
{
	if (!PyArg_ParseTuple(args, ""))
		return NULL;

	HWND hwnd = ((PyObject_Window *)self)->hwnd;
	if (!hwnd)
	{
		PyErr_SetString(PyExc_ValueError, "invalid window object.");
		return NULL;
	}

	hwnd = ::GetWindow(hwnd, GW_HWNDPREV);
	return WindowObject_FromHWND(hwnd);
}

static PyObject *Window_getNext(PyObject *self, PyObject *args)
{
	if (!PyArg_ParseTuple(args, ""))
		return NULL;

	HWND hwnd = ((PyObject_Window *)self)->hwnd;
	if (!hwnd)
	{
		PyErr_SetString(PyExc_ValueError, "invalid window object.");
		return NULL;
	}

	hwnd = ::GetWindow(hwnd, GW_HWNDNEXT);
	return WindowObject_FromHWND(hwnd);
}

static PyObject *Window_getParent(PyObject *self, PyObject *args)
{
	if (!PyArg_ParseTuple(args, ""))
		return NULL;

	HWND hwnd = ((PyObject_Window *)self)->hwnd;
	if (!hwnd)
	{
		PyErr_SetString(PyExc_ValueError, "invalid window object.");
		return NULL;
	}

	hwnd = ::GetAncestor(hwnd, GA_PARENT);
	return WindowObject_FromHWND(hwnd);
}

static PyObject *Window_getOwner(PyObject *self, PyObject *args)
{
	if (!PyArg_ParseTuple(args, ""))
		return NULL;

	HWND hwnd = ((PyObject_Window *)self)->hwnd;
	if (!hwnd)
	{
		PyErr_SetString(PyExc_ValueError, "invalid window object.");
		return NULL;
	}

	hwnd = ::GetWindow(hwnd, GW_OWNER);
	return WindowObject_FromHWND(hwnd);
}

static PyObject *Window_getLastActivePopup(PyObject *self, PyObject *args)
{
	if (!PyArg_ParseTuple(args, ""))
		return NULL;

	HWND hwnd = ((PyObject_Window *)self)->hwnd;
	if (!hwnd)
	{
		PyErr_SetString(PyExc_ValueError, "invalid window object.");
		return NULL;
	}

	hwnd = ::GetLastActivePopup(hwnd);
	return WindowObject_FromHWND(hwnd);
}

static PyObject *Window_isVisible(PyObject *self, PyObject *args)
{
	if (!PyArg_ParseTuple(args, ""))
		return NULL;

	HWND hwnd = ((PyObject_Window *)self)->hwnd;
	if (!hwnd)
	{
		PyErr_SetString(PyExc_ValueError, "invalid window object.");
		return NULL;
	}

	if (::IsWindowVisible(hwnd))
	{
		Py_INCREF(Py_True);
		return Py_True;
	}
	else
	{
		Py_INCREF(Py_False);
		return Py_False;
	}
}

static PyObject *Window_isEnabled(PyObject *self, PyObject *args)
{
	if (!PyArg_ParseTuple(args, ""))
		return NULL;

	HWND hwnd = ((PyObject_Window *)self)->hwnd;
	if (!hwnd)
	{
		PyErr_SetString(PyExc_ValueError, "invalid window object.");
		return NULL;
	}

	if (::IsWindowEnabled(hwnd))
	{
		Py_INCREF(Py_True);
		return Py_True;
	}
	else
	{
		Py_INCREF(Py_False);
		return Py_False;
	}
}

static PyObject *Window_isMinimized(PyObject *self, PyObject *args)
{
	if (!PyArg_ParseTuple(args, ""))
		return NULL;

	HWND hwnd = ((PyObject_Window *)self)->hwnd;
	if (!hwnd)
	{
		PyErr_SetString(PyExc_ValueError, "invalid window object.");
		return NULL;
	}

	if (::IsIconic(hwnd))
	{
		Py_INCREF(Py_True);
		return Py_True;
	}
	else
	{
		Py_INCREF(Py_False);
		return Py_False;
	}
}

static PyObject *Window_isMaximized(PyObject *self, PyObject *args)
{
	if (!PyArg_ParseTuple(args, ""))
		return NULL;

	HWND hwnd = ((PyObject_Window *)self)->hwnd;
	if (!hwnd)
	{
		PyErr_SetString(PyExc_ValueError, "invalid window object.");
		return NULL;
	}

	if (::IsZoomed(hwnd))
	{
		Py_INCREF(Py_True);
		return Py_True;
	}
	else
	{
		Py_INCREF(Py_False);
		return Py_False;
	}
}

static PyObject *Window_minimize(PyObject *self, PyObject *args)
{
	if (!PyArg_ParseTuple(args, ""))
		return NULL;

	HWND hwnd = ((PyObject_Window *)self)->hwnd;
	if (!hwnd)
	{
		PyErr_SetString(PyExc_ValueError, "invalid window object.");
		return NULL;
	}

	if (::SendMessage(hwnd, WM_SYSCOMMAND, SC_MINIMIZE, 0) == 0)
	{
		Py_INCREF(Py_None);
		return Py_None;
	}
	else
	{
		PyErr_SetFromWindowsErr(0);
		return NULL;
	}
}

static PyObject *Window_maximize(PyObject *self, PyObject *args)
{
	if (!PyArg_ParseTuple(args, ""))
		return NULL;

	HWND hwnd = ((PyObject_Window *)self)->hwnd;
	if (!hwnd)
	{
		PyErr_SetString(PyExc_ValueError, "invalid window object.");
		return NULL;
	}

	if (::SendMessage(hwnd, WM_SYSCOMMAND, SC_MAXIMIZE, 0) == 0)
	{
		Py_INCREF(Py_None);
		return Py_None;
	}
	else
	{
		PyErr_SetFromWindowsErr(0);
		return NULL;
	}
}

static PyObject *Window_restore(PyObject *self, PyObject *args)
{
	if (!PyArg_ParseTuple(args, ""))
		return NULL;

	HWND hwnd = ((PyObject_Window *)self)->hwnd;
	if (!hwnd)
	{
		PyErr_SetString(PyExc_ValueError, "invalid window object.");
		return NULL;
	}

	if (::SendMessage(hwnd, WM_SYSCOMMAND, SC_RESTORE, 0) == 0)
	{
		Py_INCREF(Py_None);
		return Py_None;
	}
	else
	{
		PyErr_SetFromWindowsErr(0);
		return NULL;
	}
}

static PyObject *Window_getCheck(PyObject *self, PyObject *args)
{
	if (!PyArg_ParseTuple(args, ""))
		return NULL;

	HWND hwnd = ((PyObject_Window *)self)->hwnd;
	if (!hwnd)
	{
		PyErr_SetString(PyExc_ValueError, "invalid window object.");
		return NULL;
	}

	LRESULT result = ::SendMessage(hwnd, BM_GETCHECK, 0, 0);

	switch (result)
	{
	case BST_CHECKED:
		return Py_BuildValue("i", 1);

	case BST_INDETERMINATE:
		return Py_BuildValue("i", 2);

	default:
		return Py_BuildValue("i", 0);
	}
}

static PyObject *Window_setCheck(PyObject *self, PyObject *args)
{
	int state;

	if (!PyArg_ParseTuple(args, "i", &state))
		return NULL;

	HWND hwnd = ((PyObject_Window *)self)->hwnd;
	if (!hwnd)
	{
		PyErr_SetString(PyExc_ValueError, "invalid window object.");
		return NULL;
	}

	WPARAM bst;
	switch (state)
	{
	case 0:
		bst = BST_UNCHECKED;
		break;

	case 1:
		bst = BST_CHECKED;
		break;

	case 2:
		bst = BST_INDETERMINATE;
		break;

	default:
		PyErr_SetString(PyExc_ValueError, "invalid argument.");
		return NULL;
	}

	::SendMessage(hwnd, BM_SETCHECK, bst, 0);

	Py_INCREF(Py_None);
	return Py_None;
}

static PyObject *Window_postMessage(PyObject *self, PyObject *args)
{
	int msg_id = 0;
	int msg_wparam = 0;
	int msg_lparam = 0;

	if (!PyArg_ParseTuple(args, "i|ii", &msg_id, &msg_wparam, &msg_lparam))
		return NULL;

	HWND hwnd = ((PyObject_Window *)self)->hwnd;
	if (!hwnd)
	{
		PyErr_SetString(PyExc_ValueError, "invalid window object.");
		return NULL;
	}

	if (::PostMessage(hwnd, msg_id, msg_wparam, msg_lparam))
	{
		Py_INCREF(Py_None);
		return Py_None;
	}
	else
	{
		PyErr_SetFromWindowsErr(0);
		return NULL;
	}
}

static PyObject *Window_sendMessage(PyObject *self, PyObject *args)
{
	int msg_id = 0;
	int msg_wparam = 0;
	int msg_lparam = 0;

	if (!PyArg_ParseTuple(args, "i|ii", &msg_id, &msg_wparam, &msg_lparam))
		return NULL;

	HWND hwnd = ((PyObject_Window *)self)->hwnd;
	if (!hwnd)
	{
		PyErr_SetString(PyExc_ValueError, "invalid window object.");
		return NULL;
	}

	LRESULT result = ::SendMessage(hwnd, msg_id, msg_wparam, msg_lparam);

	return Py_BuildValue("i", result);
}

static PyObject *Window_setForeground(PyObject *self, PyObject *args)
{
	int force = 0;

	if (!PyArg_ParseTuple(args, "|i", &force))
		return NULL;

	HWND hwnd = ((PyObject_Window *)self)->hwnd;
	if (!hwnd)
	{
		PyErr_SetString(PyExc_ValueError, "invalid window object.");
		return NULL;
	}

	// Bring the window to the foreground, optionally forcing the transition.
	{
		DWORD error = 0;

		int nTargetID, nForegroundID;
		DWORD sp_time = 0;

		bool thread_attached = false;
		bool fg_locktime_got = false;
		bool fg_locktime_set = false;

		// Get the thread ID of the current foreground window.
		nForegroundID = GetWindowThreadProcessId(GetForegroundWindow(), NULL);

		// Get the thread ID of the target window.
		nTargetID = GetWindowThreadProcessId(hwnd, NULL);

		if (force && nForegroundID != nTargetID)
		{
			// Attach the threads' input state.
			if (AttachThreadInput(nTargetID, nForegroundID, TRUE))
			{
				thread_attached = true;
			}
			else
			{
				printf("AttachThreadInput failed %d\n", GetLastError());
			}

			// Save the current foreground lock timeout in sp_time.
			if (SystemParametersInfo(SPI_GETFOREGROUNDLOCKTIMEOUT, 0, &sp_time, 0))
			{
				fg_locktime_got = true;
			}
			else
			{
				printf("SystemParametersInfo(SPI_GETFOREGROUNDLOCKTIMEOUT) failed %d\n", GetLastError());
			}

			// Set the foreground lock timeout to zero.
			if (fg_locktime_got)
			{
				if (SystemParametersInfo(SPI_SETFOREGROUNDLOCKTIMEOUT, 0, (LPVOID)0, 0))
				{
					fg_locktime_set = true;
				}
				else
				{
					printf("SystemParametersInfo(SPI_SETFOREGROUNDLOCKTIMEOUT) failed %d\n", GetLastError());
				}
			}
		}

		// Bring the target window to the foreground.
		if (!SetForegroundWindow(hwnd))
		{
			error = GetLastError();
			printf("SetForegroundWindow failed %d\n", error);
		}

		if (force && nForegroundID != nTargetID)
		{
			// Restore the original foreground lock timeout.
			if (fg_locktime_got && fg_locktime_set)
			{
				if (!SystemParametersInfo(SPI_SETFOREGROUNDLOCKTIMEOUT, 0, (void *)(intptr_t)sp_time, 0))
				{
					printf("SystemParametersInfo(SPI_SETFOREGROUNDLOCKTIMEOUT) failed %d\n", GetLastError());
				}
			}

			// Detach the threads' input state.
			if (thread_attached)
			{
				if (!AttachThreadInput(nTargetID, nForegroundID, FALSE))
				{
					printf("AttachThreadInput failed %d\n", GetLastError());
				}
			}
		}

		// Raise an exception if an operation failed.
		if (error)
		{
			PyErr_SetFromWindowsErr(error);
			return NULL;
		}
	}

	Py_INCREF(Py_None);
	return Py_None;
}

static PyObject *Window_getForeground(PyObject *self, PyObject *args)
{
	if (!PyArg_ParseTuple(args, ""))
		return NULL;

	HWND hwnd = ::GetForegroundWindow();
	return WindowObject_FromHWND(hwnd);
}

static PyObject *Window_setActive(PyObject *self, PyObject *args)
{
	if (!PyArg_ParseTuple(args, ""))
		return NULL;

	HWND hwnd = ((PyObject_Window *)self)->hwnd;
	if (!hwnd)
	{
		PyErr_SetString(PyExc_ValueError, "invalid window object.");
		return NULL;
	}

	SetActiveWindow(hwnd);

	Py_INCREF(Py_None);
	return Py_None;
}

static PyObject *Window_getFocus(PyObject *self, PyObject *args)
{
	if (!PyArg_ParseTuple(args, ""))
		return NULL;

	GUITHREADINFO info;
	info.cbSize = sizeof(info);

	if (!GetGUIThreadInfo(NULL, &info))
	{
		PyErr_SetFromWindowsErr(0);
		return NULL;
	}

	return WindowObject_FromHWND(info.hwndFocus);
}

static PyObject *Window_getCaret(PyObject *self, PyObject *args)
{
	if (!PyArg_ParseTuple(args, ""))
		return NULL;

	GUITHREADINFO info;
	info.cbSize = sizeof(info);

	if (!GetGUIThreadInfo(NULL, &info))
	{
		PyErr_SetFromWindowsErr(0);
		return NULL;
	}

	PyObject *pywindow = WindowObject_FromHWND(info.hwndCaret);
	if (!pywindow)
		return NULL;
	PyObject *pyret = Py_BuildValue("O(iiii)", pywindow, info.rcCaret.left, info.rcCaret.top, info.rcCaret.right, info.rcCaret.bottom);
	Py_DECREF(pywindow);
	return pyret;
}

static PyObject *Window_find(PyObject *self, PyObject *args)
{
	PyObject *pywindow_class;
	PyObject *pywindow_title;

	if (!PyArg_ParseTuple(args, "OO", &pywindow_class, &pywindow_title))
		return NULL;

	const TCHAR *p_window_class = NULL;
	const TCHAR *p_window_title = NULL;
	_tString window_class;
	_tString window_title;
	if (stringutil::PyStringTo_tString(pywindow_class, &window_class))
		p_window_class = window_class.c_str();
	if (stringutil::PyStringTo_tString(pywindow_title, &window_title))
		p_window_title = window_title.c_str();

	if (PyErr_Occurred())
		return NULL;

	HWND hwnd = ::FindWindow(p_window_class, p_window_title);
	return WindowObject_FromHWND(hwnd);
}

struct _EnumWindowsData
{
	PyObject *func;
	PyObject *arg;
};

static BOOL CALLBACK _EnumWindowsCallback(HWND hwnd, LPARAM lParam)
{
	_EnumWindowsData *data = (_EnumWindowsData *)lParam;

	PyObject *pywindow = WindowObject_FromHWND(hwnd);
	if (!pywindow)
	{
		PyErr_Print();
		return FALSE;
	}
	PyObject *pyarglist = Py_BuildValue("(OO)", pywindow, data->arg);
	Py_DECREF(pywindow);
	if (!pyarglist)
	{
		PyErr_Print();
		return FALSE;
	}
	PyObject *pyresult = PyObject_Call(data->func, pyarglist, NULL);
	Py_DECREF(pyarglist);
	if (pyresult)
	{
		int result;
		int parsed = PyArg_Parse(pyresult, "i", &result);
		Py_DECREF(pyresult);
		if (!parsed)
		{
			PyErr_Print();
			return FALSE;
		}
		return result;
	}
	else
	{
		PyErr_Print();
		return FALSE; // Stop enumeration.
	}
}

static PyObject *Window_enum(PyObject *self, PyObject *args)
{
	PyObject *func;
	PyObject *arg;

	if (!PyArg_ParseTuple(args, "OO", &func, &arg))
		return NULL;

	_EnumWindowsData data;
	data.func = func;
	data.arg = arg;

	::EnumWindows(_EnumWindowsCallback, (LPARAM)&data);

	Py_INCREF(Py_None);
	return Py_None;
}

static PyObject *Window_getDesktop(PyObject *self, PyObject *args)
{
	if (!PyArg_ParseTuple(args, ""))
		return NULL;

	HWND hwnd = ::GetDesktopWindow();

	return WindowObject_FromHWND(hwnd);
}

static PyObject *Window_fromHWND(PyObject *self, PyObject *args)
{
	PyObject *pyhwnd;

	if (!PyArg_ParseTuple(args, "O", &pyhwnd))
		return NULL;

	size_t hwnd_value = PyLong_AsSize_t(pyhwnd);
	if (PyErr_Occurred())
		return NULL;
	HWND hwnd = reinterpret_cast<HWND>(hwnd_value);

	return WindowObject_FromHWND(hwnd);
}

static BOOL CALLBACK _EnumMonitorCallback(HMONITOR hMonitor, HDC hdcMonitor, LPRECT lprcMonitor, LPARAM dwData)
{
	PyObject *monitor_info_list = (PyObject *)dwData;

	MONITORINFO mi;
	mi.cbSize = sizeof(MONITORINFO);
	GetMonitorInfo(hMonitor, &mi);

	PyObject *monitor_info = Py_BuildValue(
		"[[iiii][iiii]i]",
		mi.rcMonitor.left, mi.rcMonitor.top, mi.rcMonitor.right, mi.rcMonitor.bottom,
		mi.rcWork.left, mi.rcWork.top, mi.rcWork.right, mi.rcWork.bottom,
		mi.dwFlags);

	PyList_Append(monitor_info_list, monitor_info);

	Py_XDECREF(monitor_info);

	return TRUE;
}

static PyObject *Window_getMonitorInfo(PyObject *self, PyObject *args)
{
	if (!PyArg_ParseTuple(args, ""))
		return NULL;

	PyObject *monitor_info_list = PyList_New(0);

	EnumDisplayMonitors(NULL, NULL, _EnumMonitorCallback, (LPARAM)monitor_info_list);

	return monitor_info_list;
}

static bool Image_ByteCount(int w, int h, Py_ssize_t *byte_count)
{
	*byte_count = 0;
	if (w <= 0 || h <= 0)
		return true;
	if ((size_t)w > (size_t)PY_SSIZE_T_MAX / 3 / (size_t)h)
	{
		PyErr_SetString(PyExc_OverflowError, "image byte count exceeds Py_ssize_t range.");
		return false;
	}
	*byte_count = (Py_ssize_t)((size_t)w * 3 * (size_t)h);
	return true;
}

static PyObject_Image *Image_New(int w, int h, Py_ssize_t byte_count)
{
	PyObject_Image *image = PyObject_New(PyObject_Image, &PyType_Image);
	if (!image)
		return NULL;
	image->w = byte_count ? w : 0;
	image->h = byte_count ? h : 0;
	image->bufsize = byte_count;
	image->buf = byte_count ? malloc((size_t)byte_count) : NULL;
	if (byte_count && !image->buf)
	{
		Py_DECREF(image);
		PyErr_NoMemory();
		return NULL;
	}
	return image;
}

static void Bitmap_ConvertBGRAtoRGB(char *dst, const char *src, size_t w, size_t h, size_t wb)
{
	for (size_t y = 0; y < h; y++)
	{
		for (size_t x = 0; x < w; x++)
		{
			dst[y * w * 3 + x * 3 + 0] = src[y * wb + x * 4 + 2];
			dst[y * w * 3 + x * 3 + 1] = src[y * wb + x * 4 + 1];
			dst[y * w * 3 + x * 3 + 2] = src[y * wb + x * 4 + 0];
		}
	}
}

static void Bitmap_ConvertBGRtoRGB(char *dst, const char *src, size_t w, size_t h, size_t wb)
{
	for (size_t y = 0; y < h; y++)
	{
		for (size_t x = 0; x < w; x++)
		{
			dst[y * w * 3 + x * 3 + 0] = src[y * wb + x * 3 + 2];
			dst[y * w * 3 + x * 3 + 1] = src[y * wb + x * 3 + 1];
			dst[y * w * 3 + x * 3 + 2] = src[y * wb + x * 3 + 0];
		}
	}
}

static void Bitmap_ConvertBGR565toRGB(char *dst, const char *src, size_t w, size_t h, size_t wb)
{
	for (size_t y = 0; y < h; y++)
	{
		for (size_t x = 0; x < w; x++)
		{
			short src_pixel = *(short *)(&src[y * wb + x * 2]);
			dst[y * w * 3 + x * 3 + 0] = ((src_pixel & (0x001f << 11)) >> 11) * 255 / 0x001f;
			dst[y * w * 3 + x * 3 + 1] = ((src_pixel & (0x003f << 5)) >> 5) * 255 / 0x003f;
			dst[y * w * 3 + x * 3 + 2] = ((src_pixel & (0x001f << 0)) >> 0) * 255 / 0x001f;
		}
	}
}

static bool Bitmap_GetPixeltoRGB(char *dst, HDC dc, int w, int h)
{
	for (int y = 0; y < h; y++)
	{
		for (int x = 0; x < w; x++)
		{
			COLORREF color = ::GetPixel(dc, x, y);
			if (color == CLR_INVALID)
				return false;
			size_t offset = ((size_t)y * w + x) * 3;
			dst[offset + 0] = GetRValue(color);
			dst[offset + 1] = GetGValue(color);
			dst[offset + 2] = GetBValue(color);
		}
	}
	return true;
}

static PyObject *Window_getImage(PyObject *self, PyObject *args)
{
	if (!PyArg_ParseTuple(args, ""))
		return NULL;

	HWND hwnd = ((PyObject_Window *)self)->hwnd;
	if (!hwnd)
	{
		PyErr_SetString(PyExc_ValueError, "invalid window object.");
		return NULL;
	}

	RECT rect;
	if (!::GetWindowRect(hwnd, &rect))
	{
		PyErr_SetString(PyExc_RuntimeError, "GetWindowRect failed.");
		return NULL;
	}
	long long width = (long long)rect.right - rect.left;
	long long height = (long long)rect.bottom - rect.top;
	if (width <= 0 || height <= 0)
		return (PyObject *)Image_New(0, 0, 0);
	if (width > INT_MAX || height > INT_MAX)
	{
		PyErr_SetString(PyExc_OverflowError, "window dimensions exceed C int range.");
		return NULL;
	}
	Py_ssize_t byte_count;
	if (!Image_ByteCount((int)width, (int)height, &byte_count))
		return NULL;

	HDC dc_src = NULL, dc_dst = NULL;
	HBITMAP bitmap = NULL;
	HGDIOBJ old_bitmap = NULL;
	BITMAP bm = {};
	size_t bufsize = 0;
	void *buf = NULL;
	PyObject_Image *pyimg = NULL;
	const char *error = NULL;
	bool success = false;

	dc_src = ::GetWindowDC(hwnd);
	if (!dc_src)
	{
		error = "GetWindowDC failed.";
		goto cleanup;
	}
	dc_dst = ::CreateCompatibleDC(dc_src);
	if (!dc_dst)
	{
		error = "CreateCompatibleDC failed.";
		goto cleanup;
	}
	bitmap = ::CreateCompatibleBitmap(dc_src, (int)width, (int)height);
	if (!bitmap)
	{
		error = "CreateCompatibleBitmap failed.";
		goto cleanup;
	}
	old_bitmap = ::SelectObject(dc_dst, bitmap);
	if (!old_bitmap || old_bitmap == HGDI_ERROR)
	{
		old_bitmap = NULL;
		error = "SelectObject failed.";
		goto cleanup;
	}
	if (!::SetMapMode(dc_dst, MM_TEXT))
	{
		error = "SetMapMode failed.";
		goto cleanup;
	}
	if (!::BitBlt(dc_dst, 0, 0, (int)width, (int)height, dc_src, 0, 0, SRCCOPY))
	{
		error = "BitBlt failed.";
		goto cleanup;
	}
	if (::GetObject(bitmap, sizeof(bm), &bm) != sizeof(bm))
	{
		error = "GetObject failed.";
		goto cleanup;
	}
	if (bm.bmWidth != width || bm.bmHeight != height || bm.bmWidthBytes <= 0 || bm.bmPlanes != 1)
	{
		error = "invalid bitmap layout.";
		goto cleanup;
	}
	// GetBitmapBits accepts and returns a signed LONG byte count.
	if ((size_t)bm.bmWidthBytes > (size_t)LONG_MAX / (size_t)bm.bmHeight)
	{
		PyErr_SetString(PyExc_OverflowError, "bitmap byte count exceeds LONG range.");
		goto cleanup;
	}
	bufsize = (size_t)bm.bmWidthBytes * (size_t)bm.bmHeight;
	if ((bm.bmBitsPixel == 32 || bm.bmBitsPixel == 24 || bm.bmBitsPixel == 16) &&
		(size_t)bm.bmWidth > (size_t)bm.bmWidthBytes / (bm.bmBitsPixel / 8))
	{
		error = "invalid bitmap stride.";
		goto cleanup;
	}
	buf = malloc(bufsize);
	if (!buf)
	{
		PyErr_NoMemory();
		goto cleanup;
	}
	if (::GetBitmapBits(bitmap, (LONG)bufsize, buf) != (LONG)bufsize)
	{
		error = "GetBitmapBits failed or returned incomplete data.";
		goto cleanup;
	}
	pyimg = Image_New((int)width, (int)height, byte_count);
	if (!pyimg)
		goto cleanup;

	if (bm.bmBitsPixel == 32)
		Bitmap_ConvertBGRAtoRGB((char *)pyimg->buf, (const char *)buf, bm.bmWidth, bm.bmHeight, bm.bmWidthBytes);
	else if (bm.bmBitsPixel == 24)
		Bitmap_ConvertBGRtoRGB((char *)pyimg->buf, (const char *)buf, bm.bmWidth, bm.bmHeight, bm.bmWidthBytes);
	else if (bm.bmBitsPixel == 16)
		Bitmap_ConvertBGR565toRGB((char *)pyimg->buf, (const char *)buf, bm.bmWidth, bm.bmHeight, bm.bmWidthBytes);
	else if (!Bitmap_GetPixeltoRGB((char *)pyimg->buf, dc_dst, bm.bmWidth, bm.bmHeight))
	{
		error = "GetPixel failed.";
		goto cleanup;
	}
	success = true;

cleanup:
	if (old_bitmap)
	{
		HGDIOBJ restored = ::SelectObject(dc_dst, old_bitmap);
		if (!restored || restored == HGDI_ERROR)
		{
			if (!error)
				error = "SelectObject restore failed.";
			success = false;
		}
	}
	// Destroy the DC first even if restoring its original bitmap failed.
	if (dc_dst)
		::DeleteDC(dc_dst);
	if (bitmap)
		::DeleteObject(bitmap);
	if (dc_src)
		::ReleaseDC(hwnd, dc_src);
	free(buf);
	if (!success)
	{
		Py_XDECREF(pyimg);
		if (!PyErr_Occurred())
			PyErr_SetString(PyExc_RuntimeError, error);
		return NULL;
	}
	return (PyObject *)pyimg;
}

#define IMC_GETCONVERSIONMODE 1
#define IMC_SETCONVERSIONMODE 2
#define IMC_GETSENTENCEMODE 3
#define IMC_SETSENTENCEMODE 4
#define IMC_GETOPENSTATUS 5
#define IMC_SETOPENSTATUS 6

static PyObject *Window_getImeStatus(PyObject *self, PyObject *args)
{
	if (!PyArg_ParseTuple(args, ""))
		return NULL;

	HWND hwnd = ((PyObject_Window *)self)->hwnd;
	if (!hwnd)
	{
		PyErr_SetString(PyExc_ValueError, "invalid window object.");
		return NULL;
	}

	HWND hwnd_ime = ImmGetDefaultIMEWnd(hwnd);
	if (SendMessage(hwnd_ime, WM_IME_CONTROL, IMC_GETOPENSTATUS, 0) != 0)
	{
		Py_INCREF(Py_True);
		return Py_True;
	}
	else
	{
		Py_INCREF(Py_False);
		return Py_False;
	}
}

static PyObject *Window_setImeStatus(PyObject *self, PyObject *args)
{
	int open;

	if (!PyArg_ParseTuple(args, "i", &open))
		return NULL;

	HWND hwnd = ((PyObject_Window *)self)->hwnd;
	if (!hwnd)
	{
		PyErr_SetString(PyExc_ValueError, "invalid window object.");
		return NULL;
	}

	HWND hwnd_ime = ImmGetDefaultIMEWnd(hwnd);
	SendMessage(hwnd_ime, WM_IME_CONTROL, IMC_SETOPENSTATUS, open ? 1 : 0);

	Py_INCREF(Py_None);
	return Py_None;
}

// A timed-out provider may still be running. Never accumulate abandoned queries.
static volatile LONG ime_query_busy = 0;

struct ImeQuery
{
	volatile LONG refs = 2;
	HWND hwnd;
	HANDLE done;
	DWORD timeout;
	HRESULT result = E_FAIL;
	int composing = -1;

	void release()
	{
		if (InterlockedDecrement(&refs) == 0)
		{
			CloseHandle(done);
			delete this;
		}
	}
};

static HRESULT QueryImeComposition(ImeQuery *query)
{
	using Microsoft::WRL::ComPtr;
	ComPtr<IUIAutomation2> automation;
	HRESULT hr = CoCreateInstance(__uuidof(CUIAutomation8), NULL, CLSCTX_INPROC_SERVER,
		IID_PPV_ARGS(&automation));
	if (FAILED(hr))
		return hr;
	if (!automation)
		return E_UNEXPECTED;
	if (FAILED(hr = automation->put_ConnectionTimeout(query->timeout)) ||
		FAILED(hr = automation->put_TransactionTimeout(query->timeout)))
		return hr;
	ComPtr<IUIAutomationElement> element;
	hr = automation->ElementFromHandle(query->hwnd, &element);
	if (FAILED(hr))
		return hr;
	if (!element)
		return UIA_E_ELEMENTNOTAVAILABLE;
	// Prefer the edit descendant; its HWND host can also report keyboard focus.
	VARIANT value = {};
	value.vt = VT_BOOL;
	value.boolVal = VARIANT_TRUE;
	ComPtr<IUIAutomationCondition> condition;
	hr = automation->CreatePropertyCondition(UIA_HasKeyboardFocusPropertyId, value, &condition);
	if (FAILED(hr))
		return hr;
	if (!condition)
		return E_UNEXPECTED;
	ComPtr<IUIAutomationElement> focused;
	hr = element->FindFirst(TreeScope_Descendants, condition.Get(), &focused);
	if (FAILED(hr))
		return hr;
	if (focused)
		element = focused;
	ComPtr<IUIAutomationTextEditPattern> pattern;
	hr = element->GetCurrentPatternAs(UIA_TextEditPatternId, IID_PPV_ARGS(&pattern));
	if (FAILED(hr))
		return hr;
	if (!pattern)
		return UIA_E_NOTSUPPORTED;
	ComPtr<IUIAutomationTextRange> range;
	hr = pattern->GetActiveComposition(&range);
	if (hr != S_OK)
		return FAILED(hr) ? hr : E_UNEXPECTED;
	int compared = 0;
	if (range)
	{
		hr = range->CompareEndpoints(TextPatternRangeEndpoint_Start, range.Get(),
			TextPatternRangeEndpoint_End, &compared);
		if (hr != S_OK)
			return FAILED(hr) ? hr : E_UNEXPECTED;
	}
	query->composing = compared != 0;
	return S_OK;
}

static DWORD WINAPI ImeQueryThread(void *parameter)
{
	ImeQuery *query = static_cast<ImeQuery *>(parameter);
	HRESULT hr = CoInitializeEx(NULL, COINIT_MULTITHREADED);
	if (SUCCEEDED(hr))
	{
		query->result = QueryImeComposition(query);
		CoUninitialize();
	}
	else
		query->result = hr;
	InterlockedExchange(&ime_query_busy, 0);
	SetEvent(query->done);
	query->release();
	return 0;
}

static PyObject *Window_isImeConverting(PyObject *self, PyObject *args)
{
	int timeout = 1000;
	if (!PyArg_ParseTuple(args, "|i", &timeout))
		return NULL;
	if (timeout < 1 || timeout > 60000)
	{
		PyErr_SetString(PyExc_ValueError, "timeout must be 1..60000 milliseconds.");
		return NULL;
	}
	HWND hwnd = ((PyObject_Window *)self)->hwnd;
	DWORD process = 0;
	if (!IsWindow(hwnd) || !GetWindowThreadProcessId(hwnd, &process))
		return PyErr_SetFromWindowsErr(ERROR_INVALID_WINDOW_HANDLE);
	if (process == GetCurrentProcessId())
	{
		PyErr_SetString(PyExc_ValueError, "IME composition query requires another process.");
		return NULL;
	}
	if (InterlockedCompareExchange(&ime_query_busy, 1, 0) != 0)
		return PyErr_SetFromWindowsErr(ERROR_BUSY);
	ImeQuery *query = new (std::nothrow) ImeQuery;
	if (!query)
	{
		InterlockedExchange(&ime_query_busy, 0);
		return PyErr_NoMemory();
	}
	query->hwnd = hwnd;
	query->timeout = timeout;
	query->done = CreateEvent(NULL, TRUE, FALSE, NULL);
	HANDLE thread = query->done ? CreateThread(NULL, 0, ImeQueryThread, query, 0, NULL) : NULL;
	if (!thread)
	{
		DWORD error = GetLastError();
		if (query->done)
			CloseHandle(query->done);
		delete query;
		InterlockedExchange(&ime_query_busy, 0);
		return PyErr_SetFromWindowsErr(error);
	}
	CloseHandle(thread);
	DWORD waited, error;
	Py_BEGIN_ALLOW_THREADS
	waited = WaitForSingleObject(query->done, timeout);
	error = GetLastError();
	Py_END_ALLOW_THREADS
	HRESULT hr = E_FAIL;
	int composing = -1;
	if (waited == WAIT_OBJECT_0)
	{
		hr = query->result;
		composing = query->composing;
	}
	query->release();
	if (waited == WAIT_TIMEOUT || hr == UIA_E_TIMEOUT)
	{
		PyErr_SetString(PyExc_TimeoutError, "IME composition query timed out.");
		return NULL;
	}
	if (waited != WAIT_OBJECT_0)
		return PyErr_SetFromWindowsErr(error);
	if (hr == UIA_E_NOTSUPPORTED || hr == E_NOTIMPL || hr == REGDB_E_CLASSNOTREG)
		Py_RETURN_NONE;
	if (FAILED(hr))
		return PyErr_SetFromWindowsErr(hr);
	return PyBool_FromLong(composing);
}

static PyMethodDef Window_methods[] = {
	{"getText", Window_getText, METH_VARARGS, ""},
	{"getClassName", Window_getClassName, METH_VARARGS, ""},
	{"getProcessName", Window_getProcessName, METH_VARARGS, ""},
	{"getProcessPath", Window_getProcessPath, METH_VARARGS, ""},
	{"getHWND", Window_getHWND, METH_VARARGS, ""},
	{"getRect", Window_getRect, METH_VARARGS, ""},
	{"setRect", Window_setRect, METH_VARARGS, ""},
	{"getClientRect", Window_getClientRect, METH_VARARGS, ""},
	{"clientToScreen", Window_clientToScreen, METH_VARARGS, ""},
	{"getFirstChild", Window_getFirstChild, METH_VARARGS, ""},
	{"getLastChild", Window_getLastChild, METH_VARARGS, ""},
	{"getPrevious", Window_getPrevious, METH_VARARGS, ""},
	{"getNext", Window_getNext, METH_VARARGS, ""},
	{"getParent", Window_getParent, METH_VARARGS, ""},
	{"getOwner", Window_getOwner, METH_VARARGS, ""},
	{"getLastActivePopup", Window_getLastActivePopup, METH_VARARGS, ""},
	{"isVisible", Window_isVisible, METH_VARARGS, ""},
	{"isEnabled", Window_isEnabled, METH_VARARGS, ""},
	{"isMinimized", Window_isMinimized, METH_VARARGS, ""},
	{"isMaximized", Window_isMaximized, METH_VARARGS, ""},
	{"minimize", Window_minimize, METH_VARARGS, ""},
	{"maximize", Window_maximize, METH_VARARGS, ""},
	{"restore", Window_restore, METH_VARARGS, ""},
	{"getCheck", Window_getCheck, METH_VARARGS, ""},
	{"setCheck", Window_setCheck, METH_VARARGS, ""},
	{"postMessage", Window_postMessage, METH_VARARGS, ""},
	{"sendMessage", Window_sendMessage, METH_VARARGS, ""},
	{"setForeground", Window_setForeground, METH_VARARGS, ""},
	{"getForeground", Window_getForeground, METH_STATIC | METH_VARARGS, ""},
	{"setActive", Window_setActive, METH_VARARGS, ""},
	{"getFocus", Window_getFocus, METH_STATIC | METH_VARARGS, ""},
	{"getCaret", Window_getCaret, METH_STATIC | METH_VARARGS, ""},
	{"find", Window_find, METH_STATIC | METH_VARARGS, ""},
	{"enum", Window_enum, METH_STATIC | METH_VARARGS, ""},
	{"getDesktop", Window_getDesktop, METH_STATIC | METH_VARARGS, ""},
	{"fromHWND", Window_fromHWND, METH_STATIC | METH_VARARGS, ""},
	{"getMonitorInfo", Window_getMonitorInfo, METH_STATIC | METH_VARARGS, ""},
	{"getImage", Window_getImage, METH_VARARGS, ""},
	{"getImeStatus", Window_getImeStatus, METH_VARARGS, ""},
	{"isImeConverting", Window_isImeConverting, METH_VARARGS, ""},
	{"setImeStatus", Window_setImeStatus, METH_VARARGS, ""},
	{NULL, NULL}};

PyTypeObject pyauto::PyType_Window = {
	PyVarObject_HEAD_INIT(NULL, 0) "Window",  /* tp_name */
	sizeof(PyObject_Window),				  /* tp_basicsize */
	0,										  /* tp_itemsize */
	Window_dealloc,							  /* tp_dealloc */
	0,										  /* tp_print */
	0,										  /* tp_getattr */
	0,										  /* tp_setattr */
	0,										  /* tp_compare */
	0,										  /* tp_repr */
	0,										  /* tp_as_number */
	0,										  /* tp_as_sequence */
	0,										  /* tp_as_mapping */
	0,										  /* tp_hash */
	0,										  /* tp_call */
	0,										  /* tp_str */
	PyObject_GenericGetAttr,				  /* tp_getattro */
	PyObject_GenericSetAttr,				  /* tp_setattro */
	0,										  /* tp_as_buffer */
	Py_TPFLAGS_DEFAULT | Py_TPFLAGS_BASETYPE, /* tp_flags */
	"",										  /* tp_doc */
	0,										  /* tp_traverse */
	0,										  /* tp_clear */
	0,										  /* tp_richcompare */
	0,										  /* tp_weaklistoffset */
	0,										  /* tp_iter */
	0,										  /* tp_iternext */
	Window_methods,							  /* tp_methods */
	0,										  /* tp_members */
	0,										  /* tp_getset */
	0,										  /* tp_base */
	0,										  /* tp_dict */
	0,										  /* tp_descr_get */
	0,										  /* tp_descr_set */
	0,										  /* tp_dictoffset */
	0,										  /* tp_init */
	0,										  /* tp_alloc */
	PyType_GenericNew,						  /* tp_new */
	0,										  /* tp_free */
};

// ------------ PyObject_Image -----------------------------------------

static void Image_dealloc(PyObject *self)
{
	free(((PyObject_Image *)self)->buf);
	self->ob_type->tp_free(self);
}

static PyObject *Image_getSize(PyObject *self, PyObject *args)
{
	if (!PyArg_ParseTuple(args, ""))
		return NULL;
	return Py_BuildValue("(ii)", ((PyObject_Image *)self)->w, ((PyObject_Image *)self)->h);
}

static PyObject *Image_getMode(PyObject *self, PyObject *args)
{
	if (!PyArg_ParseTuple(args, ""))
		return NULL;
	return Py_BuildValue("s", "RGB");
}

static PyObject *Image_getBuffer(PyObject *self, PyObject *args)
{
	if (!PyArg_ParseTuple(args, ""))
		return NULL;
	return PyBytes_FromStringAndSize((const char *)((PyObject_Image *)self)->buf, ((PyObject_Image *)self)->bufsize);
}

static PyObject *Image_fromString(PyObject *self, PyObject *args)
{
	const char *mode;
	int width;
	int height;
	const char *buf;
	Py_ssize_t bufsize;

	if (!PyArg_ParseTuple(args, "s(ii)y#", &mode, &width, &height, &buf, &bufsize))
		return NULL;

	if (strcmp(mode, "RGB") != 0)
	{
		PyErr_SetString(PyExc_ValueError, "image mode unsupported.");
		return NULL;
	}

	Py_ssize_t byte_count;
	if (!Image_ByteCount(width, height, &byte_count))
		return NULL;
	if (byte_count > bufsize)
	{
		PyErr_SetString(PyExc_ValueError, "insufficient buffer length.");
		return NULL;
	}
	PyObject_Image *pyimg = Image_New(width, height, byte_count);
	if (!pyimg)
		return NULL;
	if (byte_count)
		memcpy(pyimg->buf, buf, (size_t)byte_count);

	return (PyObject *)pyimg;
}

static PyObject *Image_find(PyObject *self, PyObject *args)
{
	PyObject *obj;

	if (!PyArg_ParseTuple(args, "O", &obj))
		return NULL;

	if (!TypeCheck_Image(obj))
	{
		PyErr_SetString(PyExc_TypeError, "first argument must be a pyautocore.Image object.");
		return NULL;
	}

	PyObject_Image *img1 = (PyObject_Image *)self;
	PyObject_Image *img2 = (PyObject_Image *)obj;

	bool found = false;
	int x, y;

	for (y = 0; y <= img1->h - img2->h; y++)
	{
		for (x = 0; x <= img1->w - img2->w; x++)
		{
			bool failed = false;

			for (int y2 = 0; y2 < img2->h; y2++)
			{
				for (int x2 = 0; x2 < img2->w; x2++)
				{
					int x1 = x + x2;
					int y1 = y + y2;
					size_t offset1 = ((size_t)y1 * img1->w + x1) * 3;
					size_t offset2 = ((size_t)y2 * img2->w + x2) * 3;
					if (memcmp((const char *)img1->buf + offset1, (const char *)img2->buf + offset2, 3) != 0)
					{
						failed = true;
					}

					if (failed)
						break;
				}

				if (failed)
					break;
			}

			if (!failed)
			{
				found = true;
				break;
			}
		}

		if (found)
			break;
	}

	if (found)
	{
		PyObject *pyret = Py_BuildValue("(ii)", x, y);
		return pyret;
	}
	else
	{
		Py_INCREF(Py_None);
		return Py_None;
	}
}

static PyMethodDef Image_methods[] = {
	{"getSize", Image_getSize, METH_VARARGS, ""},
	{"getMode", Image_getMode, METH_VARARGS, ""},
	{"getBuffer", Image_getBuffer, METH_VARARGS, ""},
	{"fromString", Image_fromString, METH_STATIC | METH_VARARGS, ""},
	{"find", Image_find, METH_VARARGS, ""},
	{NULL, NULL}};

PyTypeObject pyauto::PyType_Image = {
	PyVarObject_HEAD_INIT(NULL, 0) "Image",	  /* tp_name */
	sizeof(PyObject_Image),					  /* tp_basicsize */
	0,										  /* tp_itemsize */
	Image_dealloc,							  /* tp_dealloc */
	0,										  /* tp_print */
	0,										  /* tp_getattr */
	0,										  /* tp_setattr */
	0,										  /* tp_compare */
	0,										  /* tp_repr */
	0,										  /* tp_as_number */
	0,										  /* tp_as_sequence */
	0,										  /* tp_as_mapping */
	0,										  /* tp_hash */
	0,										  /* tp_call */
	0,										  /* tp_str */
	PyObject_GenericGetAttr,				  /* tp_getattro */
	PyObject_GenericSetAttr,				  /* tp_setattro */
	0,										  /* tp_as_buffer */
	Py_TPFLAGS_DEFAULT | Py_TPFLAGS_BASETYPE, /* tp_flags */
	"",										  /* tp_doc */
	0,										  /* tp_traverse */
	0,										  /* tp_clear */
	0,										  /* tp_richcompare */
	0,										  /* tp_weaklistoffset */
	0,										  /* tp_iter */
	0,										  /* tp_iternext */
	Image_methods,							  /* tp_methods */
	0,										  /* tp_members */
	0,										  /* tp_getset */
	0,										  /* tp_base */
	0,										  /* tp_dict */
	0,										  /* tp_descr_get */
	0,										  /* tp_descr_set */
	0,										  /* tp_dictoffset */
	0,										  /* tp_init */
	0,										  /* tp_alloc */
	PyType_GenericNew,						  /* tp_new */
	0,										  /* tp_free */
};

// ------------ PyObject_Input -----------------------------------------

static int Input_init(PyObject *self, PyObject *args, PyObject *kwds)
{
	if (!PyArg_ParseTuple(args, ""))
		return -1;

	((PyObject_Input *)self)->num = 0;

	return 0;
}

#if !defined(_MSC_VER)
#define _snprintf_s(a, b, c, ...) snprintf(a, b, __VA_ARGS__)
#endif

static PyObject *Input_repr(PyObject *self)
{
	char buf[64];
	buf[0] = 0;

	switch (((PyObject_Input *)self)->num)
	{
	case 0:
		break;

	case 1:
	{
		INPUT &input = ((PyObject_Input *)self)->input[0];

		switch (input.type)
		{
		case INPUT_KEYBOARD:
		{
			if (input.ki.dwFlags & KEYEVENTF_UNICODE)
			{
				_snprintf_s(buf, sizeof(buf), _TRUNCATE, "Char(%d)", input.ki.wScan);
			}
			else if (input.ki.dwFlags & KEYEVENTF_KEYUP)
			{
				_snprintf_s(buf, sizeof(buf), _TRUNCATE, "KeyUp(%d)", input.ki.wVk);
			}
			else
			{
				_snprintf_s(buf, sizeof(buf), _TRUNCATE, "KeyDown(%d)", input.ki.wVk);
			}
		}
		break;

		case INPUT_MOUSE:
		{
			if (input.mi.dwFlags & MOUSEEVENTF_LEFTDOWN)
			{
				_snprintf_s(buf, sizeof(buf), _TRUNCATE, "MouseLeftDown(%d,%d)", input.mi.dx, input.mi.dy);
			}
			else if (input.mi.dwFlags & MOUSEEVENTF_LEFTUP)
			{
				_snprintf_s(buf, sizeof(buf), _TRUNCATE, "MouseLeftUp(%d,%d)", input.mi.dx, input.mi.dy);
			}
			else if (input.mi.dwFlags & MOUSEEVENTF_RIGHTDOWN)
			{
				_snprintf_s(buf, sizeof(buf), _TRUNCATE, "MouseRightDown(%d,%d)", input.mi.dx, input.mi.dy);
			}
			else if (input.mi.dwFlags & MOUSEEVENTF_RIGHTUP)
			{
				_snprintf_s(buf, sizeof(buf), _TRUNCATE, "MouseRightUp(%d,%d)", input.mi.dx, input.mi.dy);
			}
			else if (input.mi.dwFlags & MOUSEEVENTF_MIDDLEDOWN)
			{
				_snprintf_s(buf, sizeof(buf), _TRUNCATE, "MouseMiddleDown(%d,%d)", input.mi.dx, input.mi.dy);
			}
			else if (input.mi.dwFlags & MOUSEEVENTF_MIDDLEUP)
			{
				_snprintf_s(buf, sizeof(buf), _TRUNCATE, "MouseMiddleUp(%d,%d)", input.mi.dx, input.mi.dy);
			}
			else if (input.mi.dwFlags & MOUSEEVENTF_WHEEL)
			{
				_snprintf_s(buf, sizeof(buf), _TRUNCATE, "MouseWheel(%d,%d,%d)", input.mi.dx, input.mi.dy, input.mi.mouseData);
			}
			else if (input.mi.dwFlags & MOUSEEVENTF_HWHEEL)
			{
				_snprintf_s(buf, sizeof(buf), _TRUNCATE, "MouseHorizontalWheel(%d,%d,%d)", input.mi.dx, input.mi.dy, input.mi.mouseData);
			}
			else
			{
				_snprintf_s(buf, sizeof(buf), _TRUNCATE, "MouseMove(%d,%d)", input.mi.dx, input.mi.dy);
			}
		}
		break;
		}
	}
	break;

	case 2:
	{
		INPUT &input = ((PyObject_Input *)self)->input[0];

		switch (input.type)
		{
		case INPUT_KEYBOARD:
		{
			_snprintf_s(buf, sizeof(buf), _TRUNCATE, "Key(%d)", input.ki.wVk);
		}
		break;

		case INPUT_MOUSE:
		{
			if (input.mi.dwFlags & MOUSEEVENTF_LEFTDOWN)
			{
				_snprintf_s(buf, sizeof(buf), _TRUNCATE, "MouseLeftClick(%d,%d)", input.mi.dx, input.mi.dy);
			}
			else if (input.mi.dwFlags & MOUSEEVENTF_RIGHTDOWN)
			{
				_snprintf_s(buf, sizeof(buf), _TRUNCATE, "MouseRightClick(%d,%d)", input.mi.dx, input.mi.dy);
			}
			else if (input.mi.dwFlags & MOUSEEVENTF_MIDDLEDOWN)
			{
				_snprintf_s(buf, sizeof(buf), _TRUNCATE, "MouseMiddleClick(%d,%d)", input.mi.dx, input.mi.dy);
			}
		}
		break;
		}
	}
	break;
	}

	if (buf[0] == 0)
	{
		_snprintf_s(buf, sizeof(buf), _TRUNCATE, "<unknown Input object>");
	}

	PyObject *pyret = Py_BuildValue("s", buf);
	return pyret;
}

static int IsExtendedKey(int vk)
{
	switch (vk)
	{
	case VK_CANCEL:
	case VK_PRIOR:
	case VK_NEXT:
	case VK_END:
	case VK_HOME:
	case VK_LEFT:
	case VK_UP:
	case VK_RIGHT:
	case VK_DOWN:
	case VK_SNAPSHOT:
	case VK_INSERT:
	case VK_DELETE:
	case VK_DIVIDE:
	case VK_NUMLOCK:
	case VK_RSHIFT:
	case VK_RCONTROL:
	case VK_RMENU:
		return true;

	default:
		return false;
	}
}

static PyObject *Input_setKeyDown(PyObject *self, PyObject *args)
{
	int vk;

	if (!PyArg_ParseTuple(args, "i", &vk))
		return NULL;

	((PyObject_Input *)self)->num = 1;

	INPUT &input = ((PyObject_Input *)self)->input[0];
	input.type = INPUT_KEYBOARD;
	input.ki.wVk = (WORD)vk;
	input.ki.wScan = MapVirtualKey(vk, 0);
	input.ki.dwFlags = (IsExtendedKey(vk) ? KEYEVENTF_EXTENDEDKEY : 0);
	input.ki.dwExtraInfo = 0;
	input.ki.time = 0;

	Py_INCREF(Py_None);
	return Py_None;
}

static PyObject *Input_setKeyUp(PyObject *self, PyObject *args)
{
	int vk;

	if (!PyArg_ParseTuple(args, "i", &vk))
		return NULL;

	((PyObject_Input *)self)->num = 1;

	INPUT &input = ((PyObject_Input *)self)->input[0];
	input.type = INPUT_KEYBOARD;
	input.ki.wVk = (WORD)vk;
	input.ki.wScan = MapVirtualKey(vk, 0);
	input.ki.dwFlags = KEYEVENTF_KEYUP | (IsExtendedKey(vk) ? KEYEVENTF_EXTENDEDKEY : 0);
	input.ki.dwExtraInfo = 0;
	input.ki.time = 0;

	Py_INCREF(Py_None);
	return Py_None;
}

static PyObject *Input_setKey(PyObject *self, PyObject *args)
{
	int vk;

	if (!PyArg_ParseTuple(args, "i", &vk))
		return NULL;

	((PyObject_Input *)self)->num = 2;

	{
		INPUT &input = ((PyObject_Input *)self)->input[0];
		input.type = INPUT_KEYBOARD;
		input.ki.wVk = (WORD)vk;
		input.ki.wScan = MapVirtualKey(vk, 0);
		input.ki.dwFlags = (IsExtendedKey(vk) ? KEYEVENTF_EXTENDEDKEY : 0);
		input.ki.dwExtraInfo = 0;
		input.ki.time = 0;
	}

	{
		INPUT &input = ((PyObject_Input *)self)->input[1];
		input.type = INPUT_KEYBOARD;
		input.ki.wVk = (WORD)vk;
		input.ki.wScan = MapVirtualKey(vk, 0);
		input.ki.dwFlags = KEYEVENTF_KEYUP | (IsExtendedKey(vk) ? KEYEVENTF_EXTENDEDKEY : 0);
		input.ki.dwExtraInfo = 0;
		input.ki.time = 0;
	}

	Py_INCREF(Py_None);
	return Py_None;
}

static PyObject *Input_setChar(PyObject *self, PyObject *args)
{
	int unicode;

	if (!PyArg_ParseTuple(args, "i", &unicode))
		return NULL;

	((PyObject_Input *)self)->num = 2;

	{
		INPUT &input = ((PyObject_Input *)self)->input[0];
		input.type = INPUT_KEYBOARD;
		input.ki.wVk = 0;
		input.ki.wScan = unicode;
		input.ki.dwFlags = KEYEVENTF_UNICODE;
		input.ki.dwExtraInfo = 0;
		input.ki.time = 0;
	}

	{
		INPUT &input = ((PyObject_Input *)self)->input[1];
		input.type = INPUT_KEYBOARD;
		input.ki.wVk = 0;
		input.ki.wScan = unicode;
		input.ki.dwFlags = KEYEVENTF_UNICODE | KEYEVENTF_KEYUP;
		input.ki.dwExtraInfo = 0;
		input.ki.time = 0;
	}

	Py_INCREF(Py_None);
	return Py_None;
}

static inline int NormalizeMousePosition(int position, int origin, int size)
{
	// Target the pixel center; clamp before scaling to avoid integer overflow.
	double pixel = (double)position - origin;
	if (pixel < 0)
		pixel = 0;
	if (pixel >= size)
		pixel = size - 1;
	int normalized = (int)((pixel + 0.5) * 65536.0 / size);
	return normalized > 65535 ? 65535 : normalized;
}

static inline void MousePositionAsPixel(int *x, int *y)
{
	*x = NormalizeMousePosition(*x, GetSystemMetrics(SM_XVIRTUALSCREEN), GetSystemMetrics(SM_CXVIRTUALSCREEN));
	*y = NormalizeMousePosition(*y, GetSystemMetrics(SM_YVIRTUALSCREEN), GetSystemMetrics(SM_CYVIRTUALSCREEN));
}

static PyObject *Input_setMouseMove(PyObject *self, PyObject *args)
{
	int x, y;

	if (!PyArg_ParseTuple(args, "ii", &x, &y))
		return NULL;

	MousePositionAsPixel(&x, &y);

	((PyObject_Input *)self)->num = 1;

	INPUT &input = ((PyObject_Input *)self)->input[0];
	input.type = INPUT_MOUSE;
	input.mi.dx = x;
	input.mi.dy = y;
	input.mi.mouseData = 0;
	input.mi.dwFlags = MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK;
	input.mi.dwExtraInfo = 0;
	input.mi.time = 0;

	Py_INCREF(Py_None);
	return Py_None;
}

static PyObject *Input_setMouseLeftDown(PyObject *self, PyObject *args)
{
	int x, y;

	if (!PyArg_ParseTuple(args, "ii", &x, &y))
		return NULL;

	MousePositionAsPixel(&x, &y);

	((PyObject_Input *)self)->num = 1;

	INPUT &input = ((PyObject_Input *)self)->input[0];
	input.type = INPUT_MOUSE;
	input.mi.dx = x;
	input.mi.dy = y;
	input.mi.mouseData = 0;
	input.mi.dwFlags = MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK | MOUSEEVENTF_LEFTDOWN;
	input.mi.dwExtraInfo = 0;
	input.mi.time = 0;

	Py_INCREF(Py_None);
	return Py_None;
}

static PyObject *Input_setMouseLeftUp(PyObject *self, PyObject *args)
{
	int x, y;

	if (!PyArg_ParseTuple(args, "ii", &x, &y))
		return NULL;

	MousePositionAsPixel(&x, &y);

	((PyObject_Input *)self)->num = 1;

	INPUT &input = ((PyObject_Input *)self)->input[0];
	input.type = INPUT_MOUSE;
	input.mi.dx = x;
	input.mi.dy = y;
	input.mi.mouseData = 0;
	input.mi.dwFlags = MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK | MOUSEEVENTF_LEFTUP;
	input.mi.dwExtraInfo = 0;
	input.mi.time = 0;

	Py_INCREF(Py_None);
	return Py_None;
}

static PyObject *Input_setMouseLeftClick(PyObject *self, PyObject *args)
{
	int x, y;

	if (!PyArg_ParseTuple(args, "ii", &x, &y))
		return NULL;

	MousePositionAsPixel(&x, &y);

	((PyObject_Input *)self)->num = 2;

	{
		INPUT &input = ((PyObject_Input *)self)->input[0];
		input.type = INPUT_MOUSE;
		input.mi.dx = x;
		input.mi.dy = y;
		input.mi.mouseData = 0;
		input.mi.dwFlags = MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK | MOUSEEVENTF_LEFTDOWN;
		input.mi.dwExtraInfo = 0;
		input.mi.time = 0;
	}

	{
		INPUT &input = ((PyObject_Input *)self)->input[1];
		input.type = INPUT_MOUSE;
		input.mi.dx = x;
		input.mi.dy = y;
		input.mi.mouseData = 0;
		input.mi.dwFlags = MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK | MOUSEEVENTF_LEFTUP;
		input.mi.dwExtraInfo = 0;
		input.mi.time = 0;
	}

	Py_INCREF(Py_None);
	return Py_None;
}

static PyObject *Input_setMouseRightDown(PyObject *self, PyObject *args)
{
	int x, y;

	if (!PyArg_ParseTuple(args, "ii", &x, &y))
		return NULL;

	MousePositionAsPixel(&x, &y);

	((PyObject_Input *)self)->num = 1;

	INPUT &input = ((PyObject_Input *)self)->input[0];
	input.type = INPUT_MOUSE;
	input.mi.dx = x;
	input.mi.dy = y;
	input.mi.mouseData = 0;
	input.mi.dwFlags = MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK | MOUSEEVENTF_RIGHTDOWN;
	input.mi.dwExtraInfo = 0;
	input.mi.time = 0;

	Py_INCREF(Py_None);
	return Py_None;
}

static PyObject *Input_setMouseRightUp(PyObject *self, PyObject *args)
{
	int x, y;

	if (!PyArg_ParseTuple(args, "ii", &x, &y))
		return NULL;

	MousePositionAsPixel(&x, &y);

	((PyObject_Input *)self)->num = 1;

	INPUT &input = ((PyObject_Input *)self)->input[0];
	input.type = INPUT_MOUSE;
	input.mi.dx = x;
	input.mi.dy = y;
	input.mi.mouseData = 0;
	input.mi.dwFlags = MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK | MOUSEEVENTF_RIGHTUP;
	input.mi.dwExtraInfo = 0;
	input.mi.time = 0;

	Py_INCREF(Py_None);
	return Py_None;
}

static PyObject *Input_setMouseRightClick(PyObject *self, PyObject *args)
{
	int x, y;

	if (!PyArg_ParseTuple(args, "ii", &x, &y))
		return NULL;

	MousePositionAsPixel(&x, &y);

	((PyObject_Input *)self)->num = 2;

	{
		INPUT &input = ((PyObject_Input *)self)->input[0];
		input.type = INPUT_MOUSE;
		input.mi.dx = x;
		input.mi.dy = y;
		input.mi.mouseData = 0;
		input.mi.dwFlags = MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK | MOUSEEVENTF_RIGHTDOWN;
		input.mi.dwExtraInfo = 0;
		input.mi.time = 0;
	}

	{
		INPUT &input = ((PyObject_Input *)self)->input[1];
		input.type = INPUT_MOUSE;
		input.mi.dx = x;
		input.mi.dy = y;
		input.mi.mouseData = 0;
		input.mi.dwFlags = MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK | MOUSEEVENTF_RIGHTUP;
		input.mi.dwExtraInfo = 0;
		input.mi.time = 0;
	}

	Py_INCREF(Py_None);
	return Py_None;
}

static PyObject *Input_setMouseMiddleDown(PyObject *self, PyObject *args)
{
	int x, y;

	if (!PyArg_ParseTuple(args, "ii", &x, &y))
		return NULL;

	MousePositionAsPixel(&x, &y);

	((PyObject_Input *)self)->num = 1;

	INPUT &input = ((PyObject_Input *)self)->input[0];
	input.type = INPUT_MOUSE;
	input.mi.dx = x;
	input.mi.dy = y;
	input.mi.mouseData = 0;
	input.mi.dwFlags = MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK | MOUSEEVENTF_MIDDLEDOWN;
	input.mi.dwExtraInfo = 0;
	input.mi.time = 0;

	Py_INCREF(Py_None);
	return Py_None;
}

static PyObject *Input_setMouseMiddleUp(PyObject *self, PyObject *args)
{
	int x, y;

	if (!PyArg_ParseTuple(args, "ii", &x, &y))
		return NULL;

	MousePositionAsPixel(&x, &y);

	((PyObject_Input *)self)->num = 1;

	INPUT &input = ((PyObject_Input *)self)->input[0];
	input.type = INPUT_MOUSE;
	input.mi.dx = x;
	input.mi.dy = y;
	input.mi.mouseData = 0;
	input.mi.dwFlags = MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK | MOUSEEVENTF_MIDDLEUP;
	input.mi.dwExtraInfo = 0;
	input.mi.time = 0;

	Py_INCREF(Py_None);
	return Py_None;
}

static PyObject *Input_setMouseMiddleClick(PyObject *self, PyObject *args)
{
	int x, y;

	if (!PyArg_ParseTuple(args, "ii", &x, &y))
		return NULL;

	MousePositionAsPixel(&x, &y);

	((PyObject_Input *)self)->num = 2;

	{
		INPUT &input = ((PyObject_Input *)self)->input[0];
		input.type = INPUT_MOUSE;
		input.mi.dx = x;
		input.mi.dy = y;
		input.mi.mouseData = 0;
		input.mi.dwFlags = MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK | MOUSEEVENTF_MIDDLEDOWN;
		input.mi.dwExtraInfo = 0;
		input.mi.time = 0;
	}

	{
		INPUT &input = ((PyObject_Input *)self)->input[1];
		input.type = INPUT_MOUSE;
		input.mi.dx = x;
		input.mi.dy = y;
		input.mi.mouseData = 0;
		input.mi.dwFlags = MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK | MOUSEEVENTF_MIDDLEUP;
		input.mi.dwExtraInfo = 0;
		input.mi.time = 0;
	}

	Py_INCREF(Py_None);
	return Py_None;
}

static PyObject *Input_setMouseWheel(PyObject *self, PyObject *args)
{
	int x, y;
	float wheel;

	if (!PyArg_ParseTuple(args, "iif", &x, &y, &wheel))
		return NULL;

	MousePositionAsPixel(&x, &y);

	((PyObject_Input *)self)->num = 1;

	INPUT &input = ((PyObject_Input *)self)->input[0];
	input.type = INPUT_MOUSE;
	input.mi.dx = x;
	input.mi.dy = y;
	input.mi.mouseData = (DWORD)(wheel * WHEEL_DELTA);
	input.mi.dwFlags = MOUSEEVENTF_WHEEL | MOUSEEVENTF_ABSOLUTE;
	input.mi.dwExtraInfo = 0;
	input.mi.time = 0;

	Py_INCREF(Py_None);
	return Py_None;
}

static PyObject *Input_setMouseHorizontalWheel(PyObject *self, PyObject *args)
{
	int x, y;
	float wheel;

	if (!PyArg_ParseTuple(args, "iif", &x, &y, &wheel))
		return NULL;

	MousePositionAsPixel(&x, &y);

	((PyObject_Input *)self)->num = 1;

	INPUT &input = ((PyObject_Input *)self)->input[0];
	input.type = INPUT_MOUSE;
	input.mi.dx = x;
	input.mi.dy = y;
	input.mi.mouseData = (DWORD)(wheel * WHEEL_DELTA);
	input.mi.dwFlags = MOUSEEVENTF_HWHEEL | MOUSEEVENTF_ABSOLUTE;
	input.mi.dwExtraInfo = 0;
	input.mi.time = 0;

	Py_INCREF(Py_None);
	return Py_None;
}

static PyObject *Input_send(PyObject *self, PyObject *args)
{
	PyObject *py_input_list;

	if (!PyArg_ParseTuple(args, "O", &py_input_list))
		return NULL;

	if (!PyTuple_Check(py_input_list) && !PyList_Check(py_input_list))
	{
		PyErr_SetString(PyExc_TypeError, "argument must be a tuple or list.");
		return NULL;
	}

	Py_ssize_t item_num = PySequence_Length(py_input_list);
	if (item_num < 0)
		return NULL;
	if (item_num > INT_MAX / 2)
		return PyErr_NoMemory();

	INPUT *input = new (std::nothrow) INPUT[item_num * 2];
	if (!input)
		return PyErr_NoMemory();
	int num_input = 0;

	for (int i = 0; i < item_num; i++)
	{
		PyObject *pyitem = PySequence_GetItem(py_input_list, i);
		if (!pyitem)
		{
			delete[] input;
			return NULL;
		}

		if (!TypeCheck_Input(pyitem))
		{
			Py_DECREF(pyitem);
			PyErr_SetString(PyExc_TypeError, "argument must be a sequence of Input object.");
			delete[] input;
			return NULL;
		}

		// Give synthetic input the timestamp of the last received input event.
		// Mark dwExtraInfo so hooks can recognize events injected by this module.
		for (int k = 0; k < ((PyObject_Input *)pyitem)->num; k++)
		{
			input[num_input] = ((PyObject_Input *)pyitem)->input[k];

			switch (input[num_input].type)
			{
			case INPUT_MOUSE:
				input[num_input].mi.time = g.last_key_time;
				input[num_input].mi.dwExtraInfo = (ULONG_PTR)g.module_handle;
				break;

			case INPUT_KEYBOARD:
				input[num_input].ki.time = g.last_key_time;
				input[num_input].ki.dwExtraInfo = (ULONG_PTR)g.module_handle;
				break;
			}

			++num_input;
		}

		Py_DECREF(pyitem);
	}

	UINT num_sent = SendInput(num_input, input, sizeof(INPUT));

	delete[] input;

	if (num_sent != num_input)
	{
		PyErr_Format(PyExc_WindowsError, "SendInput failed : num_input=%d, num_sent=%d, errno=%d", num_input, num_sent, GetLastError());
		return NULL;
	}

	Py_INCREF(Py_None);
	return Py_None;
}

static PyObject *Input_getCursorPos(PyObject *self, PyObject *args)
{
	if (!PyArg_ParseTuple(args, ""))
		return NULL;

	POINT pos;
	GetCursorPos(&pos);

	PyObject *pyret = Py_BuildValue("(ii)", pos.x, pos.y);
	return pyret;
}

static PyObject *Input_getKeyboardState(PyObject *self, PyObject *args)
{
	if (!PyArg_ParseTuple(args, ""))
		return NULL;

	BYTE buf[256];
	if (!GetKeyboardState(buf))
	{
		PyErr_SetFromWindowsErr(0);
		return NULL;
	}

	PyObject *pyret = Py_BuildValue("y#", buf, sizeof(buf));
	return pyret;
}

static PyObject *Input_setKeyboardState(PyObject *self, PyObject *args)
{
	BYTE *buf;
	Py_ssize_t bufsize;

	if (!PyArg_ParseTuple(args, "s#", &buf, &bufsize))
		return NULL;

	if (bufsize != 256)
	{
		PyErr_SetString(PyExc_ValueError, "keyboard state must contain 256 bytes.");
		return NULL;
	}

	if (!SetKeyboardState(buf))
	{
		PyErr_SetFromWindowsErr(0);
		return NULL;
	}

	Py_INCREF(Py_None);
	return Py_None;
}

static PyObject *Input_getKeyState(PyObject *self, PyObject *args)
{
	int vk;
	if (!PyArg_ParseTuple(args, "i", &vk))
		return NULL;

	SHORT state = GetKeyState(vk);

	PyObject *pyret = Py_BuildValue("H", (USHORT)state);
	return pyret;
}

static PyObject *Input_getAsyncKeyState(PyObject *self, PyObject *args)
{
	int vk;
	if (!PyArg_ParseTuple(args, "i", &vk))
		return NULL;

	SHORT state = GetAsyncKeyState(vk);

	PyObject *pyret = Py_BuildValue("H", (USHORT)state);
	return pyret;
}

static PyMethodDef Input_methods[] = {
	{"setKeyDown", Input_setKeyDown, METH_VARARGS, ""},
	{"setKeyUp", Input_setKeyUp, METH_VARARGS, ""},
	{"setKey", Input_setKey, METH_VARARGS, ""},
	{"setChar", Input_setChar, METH_VARARGS, ""},
	{"setMouseMove", Input_setMouseMove, METH_VARARGS, ""},
	{"setMouseLeftDown", Input_setMouseLeftDown, METH_VARARGS, ""},
	{"setMouseLeftUp", Input_setMouseLeftUp, METH_VARARGS, ""},
	{"setMouseLeftClick", Input_setMouseLeftClick, METH_VARARGS, ""},
	{"setMouseRightDown", Input_setMouseRightDown, METH_VARARGS, ""},
	{"setMouseRightUp", Input_setMouseRightUp, METH_VARARGS, ""},
	{"setMouseRightClick", Input_setMouseRightClick, METH_VARARGS, ""},
	{"setMouseMiddleDown", Input_setMouseMiddleDown, METH_VARARGS, ""},
	{"setMouseMiddleUp", Input_setMouseMiddleUp, METH_VARARGS, ""},
	{"setMouseMiddleClick", Input_setMouseMiddleClick, METH_VARARGS, ""},
	{"setMouseWheel", Input_setMouseWheel, METH_VARARGS, ""},
	{"setMouseHorizontalWheel", Input_setMouseHorizontalWheel, METH_VARARGS, ""},
	{"send", Input_send, METH_STATIC | METH_VARARGS, ""},
	{"getCursorPos", Input_getCursorPos, METH_STATIC | METH_VARARGS, ""},
	{"getKeyboardState", Input_getKeyboardState, METH_STATIC | METH_VARARGS, ""},
	{"setKeyboardState", Input_setKeyboardState, METH_STATIC | METH_VARARGS, ""},
	{"getKeyState", Input_getKeyState, METH_STATIC | METH_VARARGS, ""},
	{"getAsyncKeyState", Input_getAsyncKeyState, METH_STATIC | METH_VARARGS, ""},
	{NULL, NULL}};

PyTypeObject pyauto::PyType_Input = {
	PyVarObject_HEAD_INIT(NULL, 0) "Input",	  /* tp_name */
	sizeof(PyObject_Input),					  /* tp_basicsize */
	0,										  /* tp_itemsize */
	0,										  /* tp_dealloc */
	0,										  /* tp_print */
	0,										  /* tp_getattr */
	0,										  /* tp_setattr */
	0,										  /* tp_compare */
	Input_repr,								  /* tp_repr */
	0,										  /* tp_as_number */
	0,										  /* tp_as_sequence */
	0,										  /* tp_as_mapping */
	0,										  /* tp_hash */
	0,										  /* tp_call */
	0,										  /* tp_str */
	PyObject_GenericGetAttr,				  /* tp_getattro */
	PyObject_GenericSetAttr,				  /* tp_setattro */
	0,										  /* tp_as_buffer */
	Py_TPFLAGS_DEFAULT | Py_TPFLAGS_BASETYPE, /* tp_flags */
	"",										  /* tp_doc */
	0,										  /* tp_traverse */
	0,										  /* tp_clear */
	0,										  /* tp_richcompare */
	0,										  /* tp_weaklistoffset */
	0,										  /* tp_iter */
	0,										  /* tp_iternext */
	Input_methods,							  /* tp_methods */
	0,										  /* tp_members */
	0,										  /* tp_getset */
	0,										  /* tp_base */
	0,										  /* tp_dict */
	0,										  /* tp_descr_get */
	0,										  /* tp_descr_set */
	0,										  /* tp_dictoffset */
	Input_init,								  /* tp_init */
	0,										  /* tp_alloc */
	PyType_GenericNew,						  /* tp_new */
	0,										  /* tp_free */
};

// ------------ PyObject_Hook -----------------------------------------

// Convert keyboard-hook flags to synthetic-input flags.
static int flags_conv(DWORD flags)
{
	int ret = 0;
	if (flags & LLKHF_EXTENDED)
		ret |= KEYEVENTF_EXTENDEDKEY;
	if (flags & LLKHF_UP)
		ret |= KEYEVENTF_KEYUP;
	return ret;
}

static LRESULT CALLBACK Hook_wndProc(HWND hWnd, UINT message, WPARAM wParam, LPARAM lParam)
{
	PythonUtil::GIL_Ensure gil_ensure;

	switch (message)
	{
	case WM_CREATE:
		break;

	case WM_DESTROY:
		break;

	case WM_CLIPBOARDUPDATE:
		return Hook_Clipboard_wndProc(hWnd, message, wParam, lParam);
		break;

	default:
		return DefWindowProc(hWnd, message, wParam, lParam);
	}
	return 0;
}

static int Hook_init(PyObject *self, PyObject *args, PyObject *kwds)
{
	if (!PyArg_ParseTuple(args, ""))
		return -1;

	if (g.pyhook)
	{
		PyErr_SetString(PyExc_ValueError, "a Hook is already active.");
		return -1;
	}

	// Register the window class.
	{
		WNDCLASSEX wcex;

		wcex.cbSize = sizeof(WNDCLASSEX);

		wcex.style = CS_HREDRAW | CS_VREDRAW;
		wcex.lpfnWndProc = (WNDPROC)Hook_wndProc;
		wcex.cbClsExtra = 0;
		wcex.cbWndExtra = 0;
		wcex.hInstance = g.module_handle;
		wcex.hIcon = 0;
		wcex.hCursor = 0;
		wcex.hbrBackground = (HBRUSH)(COLOR_WINDOW + 1);
		wcex.lpszMenuName = 0;
		wcex.lpszClassName = _T(PYAUTO_WINDOW_NAME);
		wcex.hIconSm = 0;

		if (!RegisterClassEx(&wcex) && GetLastError() != ERROR_CLASS_ALREADY_EXISTS)
		{
			PyErr_SetFromWindowsErr(0);
			return -1;
		}
	}

	// Create a window to receive hook events.
	g.pyauto_window = CreateWindow(_T(PYAUTO_WINDOW_NAME), _T(PYAUTO_WINDOW_NAME), WS_OVERLAPPEDWINDOW, CW_USEDEFAULT, 0, CW_USEDEFAULT, 0, NULL, NULL, g.module_handle, NULL);

	if (!g.pyauto_window)
	{
		PyErr_SetFromWindowsErr(0);
		return -1;
	}

	// Record the Hook object only after construction succeeds.
	g.pyhook = (PyObject_Hook *)self;

	return 0;
}

static void _Hook_destroy(PyObject_Hook *self)
{
	if (g.pyhook == self)
	{
		HookEnd_Key();
		HookEnd_Mouse();
		HookEnd_Clipboard();

		HWND window = g.pyauto_window;
		g.pyauto_window = NULL;
		g.pyhook = NULL;
		DestroyWindow(window);
	}

	// Invalidate every callback before releasing references that may reenter Python.
	PyObject *callbacks[] = {self->keydown, self->keyup, self->mousedown, self->mouseup,
		self->mousedblclk, self->mousemove, self->mousewheel, self->mousehorizontalwheel, self->clipboard};
	self->keydown = self->keyup = self->mousedown = self->mouseup = NULL;
	self->mousedblclk = self->mousemove = self->mousewheel = self->mousehorizontalwheel = self->clipboard = NULL;
	for (PyObject *callback : callbacks)
		Py_XDECREF(callback);
}

static void Hook_dealloc(PyObject *self)
{
	_Hook_destroy((PyObject_Hook *)self);
	self->ob_type->tp_free(self);
}

static PyObject *Hook_destroy(PyObject *self, PyObject *args)
{
	if (!PyArg_ParseTuple(args, ""))
		return NULL;

	_Hook_destroy((PyObject_Hook *)self);
	Py_RETURN_NONE;
}

static PyObject *Hook_getattr(PyObject_Hook *self, PyObject *pyattrname)
{
	wchar_t *buffer = PyUnicode_AsWideCharString(pyattrname, NULL);
	if (!buffer)
		return NULL;
	std::wstring attrname_storage = buffer;
	PyMem_Free(buffer);
	const wchar_t *attrname = attrname_storage.c_str();

	if (attrname[0] == 'k' && wcscmp(attrname, L"keydown") == 0)
	{
		if (self->keydown)
		{
			Py_INCREF(self->keydown);
			return self->keydown;
		}
		else
		{
			Py_INCREF(Py_None);
			return Py_None;
		}
	}
	else if (attrname[0] == 'k' && wcscmp(attrname, L"keyup") == 0)
	{
		if (self->keyup)
		{
			Py_INCREF(self->keyup);
			return self->keyup;
		}
		else
		{
			Py_INCREF(Py_None);
			return Py_None;
		}
	}
	else if (attrname[0] == 'm' && wcscmp(attrname, L"mousedown") == 0)
	{
		if (self->mousedown)
		{
			Py_INCREF(self->mousedown);
			return self->mousedown;
		}
		else
		{
			Py_INCREF(Py_None);
			return Py_None;
		}
	}
	else if (attrname[0] == 'm' && wcscmp(attrname, L"mouseup") == 0)
	{
		if (self->mouseup)
		{
			Py_INCREF(self->mouseup);
			return self->mouseup;
		}
		else
		{
			Py_INCREF(Py_None);
			return Py_None;
		}
	}
	else if (attrname[0] == 'm' && wcscmp(attrname, L"mousedblclk") == 0)
	{
		if (self->mousedblclk)
		{
			Py_INCREF(self->mousedblclk);
			return self->mousedblclk;
		}
		else
		{
			Py_INCREF(Py_None);
			return Py_None;
		}
	}
	else if (attrname[0] == 'm' && wcscmp(attrname, L"mousemove") == 0)
	{
		if (self->mousemove)
		{
			Py_INCREF(self->mousemove);
			return self->mousemove;
		}
		else
		{
			Py_INCREF(Py_None);
			return Py_None;
		}
	}
	else if (attrname[0] == 'm' && wcscmp(attrname, L"mousewheel") == 0)
	{
		if (self->mousewheel)
		{
			Py_INCREF(self->mousewheel);
			return self->mousewheel;
		}
		else
		{
			Py_INCREF(Py_None);
			return Py_None;
		}
	}
	else if (attrname[0] == 'm' && wcscmp(attrname, L"mousehorizontalwheel") == 0)
	{
		if (self->mousehorizontalwheel)
		{
			Py_INCREF(self->mousehorizontalwheel);
			return self->mousehorizontalwheel;
		}
		else
		{
			Py_INCREF(Py_None);
			return Py_None;
		}
	}
	else if (attrname[0] == 'c' && wcscmp(attrname, L"clipboard") == 0)
	{
		if (self->clipboard)
		{
			Py_INCREF(self->clipboard);
			return self->clipboard;
		}
		else
		{
			Py_INCREF(Py_None);
			return Py_None;
		}
	}
	else
	{
		return PyObject_GenericGetAttr((PyObject *)self, pyattrname);
	}
}

static int Hook_setattr(PyObject_Hook *self, PyObject *pyattrname, PyObject *pyvalue)
{
	const char *name;
	if (!PyArg_Parse(pyattrname, "s", &name))
		return -1;

	const char *names[] = {"keydown", "keyup", "mousedown", "mouseup", "mousedblclk",
		"mousemove", "mousewheel", "mousehorizontalwheel", "clipboard"};
	PyObject **callbacks[] = {&self->keydown, &self->keyup, &self->mousedown, &self->mouseup,
		&self->mousedblclk, &self->mousemove, &self->mousewheel, &self->mousehorizontalwheel, &self->clipboard};
	for (int i = 0; i < 9; i++)
	{
		if (strcmp(name, names[i]) != 0)
			continue;
		if (g.pyhook != self)
		{
			PyErr_SetString(PyExc_ValueError, "Hook has been destroyed or is not active.");
			return -1;
		}
		if (!pyvalue)
		{
			PyErr_SetString(PyExc_AttributeError, "set callback to None instead of deleting it.");
			return -1;
		}

		PyObject *value = pyvalue == Py_None ? NULL : Py_NewRef(pyvalue);
		Py_XSETREF(*callbacks[i], value);
		// Releasing the previous callable can destroy this Hook or create its replacement.
		if (g.pyhook != self)
			return 0;
		if (value)
		{
			if (i < 2)
				HookStart_Key();
			else if (i < 8)
				HookStart_Mouse();
			else
				HookStart_Clipboard();
		}
		else if (i == 8)
			HookEnd_Clipboard();
		return 0;
	}
	return PyObject_GenericSetAttr((PyObject *)self, pyattrname, pyvalue);
}

static PyObject *Hook_reset(PyObject_Hook *self, PyObject *args)
{
	if (!PyArg_ParseTuple(args, ""))
		return NULL;

	if (g.pyhook != self)
	{
		PyErr_SetString(PyExc_ValueError, "Hook has been destroyed or is not active.");
		return NULL;
	}

	// Uninstall hooks.
	{
		PythonUtil_DebugPrintf("unset hook\n");

		HookEnd_Key();
		HookEnd_Mouse();
		HookEnd_Clipboard();
	}

	// Restart hooks.
	{
		PythonUtil_DebugPrintf("set hook\n");

		if (self->keydown || self->keyup)
		{
			HookStart_Key();
		}

		if (self->mousedown || self->mouseup || self->mousedblclk || self->mousemove || self->mousewheel || self->mousehorizontalwheel)
		{
			HookStart_Mouse();
		}

		HookStart_Clipboard();
	}

	Py_INCREF(Py_None);
	return Py_None;
}

static PyMethodDef Hook_methods[] = {
	{"destroy", Hook_destroy, METH_VARARGS, ""},
	{"reset", (PyCFunction)Hook_reset, METH_VARARGS, ""},
	{NULL, NULL}};

PyTypeObject pyauto::PyType_Hook = {
	PyVarObject_HEAD_INIT(NULL, 0) "Hook",	  /* tp_name */
	sizeof(PyObject_Hook),					  /* tp_basicsize */
	0,										  /* tp_itemsize */
	Hook_dealloc,							  /* tp_dealloc */
	0,										  /* tp_print */
	0,										  /* tp_getattr */
	0,										  /* tp_setattr */
	0,										  /* tp_compare */
	0,										  /* tp_repr */
	0,										  /* tp_as_number */
	0,										  /* tp_as_sequence */
	0,										  /* tp_as_mapping */
	0,										  /* tp_hash */
	0,										  /* tp_call */
	0,										  /* tp_str */
	(getattrofunc)Hook_getattr,				  /* tp_getattro */
	(setattrofunc)Hook_setattr,				  /* tp_setattro */
	0,										  /* tp_as_buffer */
	Py_TPFLAGS_DEFAULT | Py_TPFLAGS_BASETYPE, /* tp_flags */
	"",										  /* tp_doc */
	0,										  /* tp_traverse */
	0,										  /* tp_clear */
	0,										  /* tp_richcompare */
	0,										  /* tp_weaklistoffset */
	0,										  /* tp_iter */
	0,										  /* tp_iternext */
	Hook_methods,							  /* tp_methods */
	0,										  /* tp_members */
	0,										  /* tp_getset */
	0,										  /* tp_base */
	0,										  /* tp_dict */
	0,										  /* tp_descr_get */
	0,										  /* tp_descr_set */
	0,										  /* tp_dictoffset */
	Hook_init,								  /* tp_init */
	0,										  /* tp_alloc */
	PyType_GenericNew,						  /* tp_new */
	0,										  /* tp_free */
};

// ------------ global function -----------------------------------------

static PyObject *_shellExecute(PyObject *self, PyObject *args)
{
	BOOL result;
	DWORD shell_error = ERROR_SUCCESS;
	PyObject *pyverb;
	PyObject *pyfile;
	PyObject *pyparam = NULL;
	PyObject *pydirectory = NULL;
	PyObject *pyswmode = NULL;

	if (!PyArg_ParseTuple(args, "OO|OOO", &pyverb, &pyfile, &pyparam, &pydirectory, &pyswmode))
		return NULL;

	const TCHAR *p_file = NULL;
	const TCHAR *p_verb = NULL;
	const TCHAR *p_param = NULL;
	const TCHAR *p_directory = NULL;
	const TCHAR *p_swmode = NULL;

	_tString verb;
	_tString file;
	_tString param;
	_tString directory;
	_tString swmode;

	if (stringutil::PyStringTo_tString(pyverb, &verb))
		p_verb = verb.c_str();

	if (stringutil::PyStringTo_tString(pyfile, &file))
		p_file = file.c_str();

	if (pyparam && stringutil::PyStringTo_tString(pyparam, &param))
		p_param = param.c_str();

	if (pydirectory && stringutil::PyStringTo_tString(pydirectory, &directory))
		p_directory = directory.c_str();

	if (pyswmode && stringutil::PyStringTo_tString(pyswmode, &swmode))
		p_swmode = swmode.c_str();

	if (PyErr_Occurred())
		return NULL;

	SHELLEXECUTEINFO sei;
	ZeroMemory(&sei, sizeof(SHELLEXECUTEINFO));
	sei.cbSize = sizeof(SHELLEXECUTEINFO);
	sei.fMask = SEE_MASK_INVOKEIDLIST | SEE_MASK_FLAG_NO_UI | SEE_MASK_NOASYNC;
	sei.hwnd = NULL;
	sei.lpVerb = p_verb;
	sei.lpFile = p_file;
	sei.lpParameters = p_param;
	sei.lpDirectory = p_directory;

	if (p_swmode == NULL || swmode == _T("") || swmode == _T("normal"))
	{
		sei.nShow = SW_SHOWNORMAL;
	}
	else if (swmode == _T("minimized"))
	{
		sei.nShow = SW_SHOWMINIMIZED;
	}
	else if (swmode == _T("maximized"))
	{
		sei.nShow = SW_SHOWMAXIMIZED;
	}
	else
	{
		PyErr_SetString(PyExc_ValueError, "invalid show mode.");
		return NULL;
	}

	Py_BEGIN_ALLOW_THREADS
		result = ShellExecuteEx(&sei);
		if (!result) shell_error = GetLastError();
	Py_END_ALLOW_THREADS

		if (result)
	{
		Py_INCREF(Py_None);
		return Py_None;
	}
	else
	{
		PyErr_SetFromWindowsErr(shell_error);
		return NULL;
	}
}

static PyObject *_messageLoop(PyObject *self, PyObject *args)
{
	if (!PyArg_ParseTuple(args, ""))
		return NULL;

	MSG msg;
	for (;;)
	{
		while (PeekMessage(&msg, NULL, 0, 0, PM_REMOVE))
		{
			if (msg.message == WM_QUIT)
			{
				goto end;
			}

			TranslateMessage(&msg);
			DispatchMessage(&msg);
		}

		Py_BEGIN_ALLOW_THREADS

		WaitMessage();

		Py_END_ALLOW_THREADS
	}

end:

	Py_INCREF(Py_None);
	return Py_None;
}

static PyObject *_setDebug(PyObject *self, PyObject *args)
{
	int enabled;

	if (!PyArg_ParseTuple(args, "i", &enabled))
		return NULL;

	g.debug = enabled != 0;

	Py_INCREF(Py_None);
	return Py_None;
}

/**
@cond japanese
@page pyauto_native pyautoネイティブAPI

import pyautoで使う現在のネイティブ契約です。入力の短縮クラスは@ref pyautoinput 、整数定数は@ref pyautoconst を参照してください。
表ではselfを省略し、インスタンス操作も型名で示します（実際はtarget.getText()等）。静的操作は型から呼びます。
ネイティブ関数・メソッドは位置引数だけを受けます。整数は明記した幅へ収まり、文字列にはNULを含めないでください（長さ付きInput.setKeyboardStateは除く）。文字列引数とHook属性名の埋め込みNULはValueErrorです。
isImeConvertingの照会ワーカーを除き、各OS操作は呼出しスレッドで同期実行されます。ブロックする送信・Shell操作をUIイベントやフックへ持ち込まないでください。
通常のランチャー登録にはMainWindow.ShellExecuteCommandや既存キーマップを先に使えます。
Errorは公開例外型ですが、ここに挙げた失敗をすべてpyauto.Errorで捕捉できるわけではありません。


@section pyauto_Window Window
fromHWND/find/getForeground等から取得し、Window()を直接構築しません。ラッパーはOS窓を所有・破棄しません。
HWND=0はNoneです。インスタンス操作は保持HWNDが0ならValueErrorですが、非0のHWNDが現在有効かは検証しません。
同じHWNDの既存ラッパーがある間は再利用します。OSで破棄/再使用されたハンドルは古くなり得るため、不要な参照を保持しません。
getCaretの戻り値やenumの引数を保存しなければ、これらの呼出しがラッパーを保持し続けることはありません。
OS照会の失敗は一律に例外化されません。このAPIだけで窓の寿命を検証しないでください。
setRectはトップレベル窓には画面座標、子窓には親クライアント座標を使います。
enumコールバックは呼出側で同期実行し、NoneではなくC intを返します。短い処理にしてください。

| 呼出し（self省略） | 種別 | 契約 |
|---|---|---|
| `Window.getText()` | instance | タイトルをstrで取得。 |
| `Window.getClassName()` | instance | ウィンドウクラス名をstrで取得。最大255 UTF-16コード単位。Win32取得失敗時は空文字列。 |
| `Window.getProcessName()` | instance | 所有プロセスの実行ファイル末尾名をstrで取得。スナップショット失敗はOSError。 |
| `Window.getProcessPath()` | instance | 所有プロセスの実行ファイルパスをstrで取得。アクセス/列挙失敗はOSError。 |
| `Window.getHWND()` | instance | 保持するHWNDをポインター幅の整数で返す。 |
| `Window.getRect()` | instance | 画面ピクセルの(left, top, right, bottom)。右・下は除外。 |
| `Window.setRect(rect)` | instance | 4整数のシーケンスで位置/サイズを変更。成功None、MoveWindow失敗はOSError。子窓では親クライアント座標を使う。 |
| `Window.getClientRect()` | instance | クライアントピクセルの(left, top, right, bottom)。 |
| `Window.clientToScreen(x, y)` | instance | クライアントピクセルを画面ピクセルの(x, y)へ変換。 |
| `Window.getFirstChild()` | instance | 最初の子窓またはNone。 |
| `Window.getLastChild()` | instance | 最後の子窓またはNone。 |
| `Window.getPrevious()` | instance | Z順で前の窓またはNone。 |
| `Window.getNext()` | instance | Z順で次の窓またはNone。 |
| `Window.getParent()` | instance | GA_PARENTの親窓またはNone。 |
| `Window.getOwner()` | instance | 所有窓またはNone。親子関係とは別。 |
| `Window.getLastActivePopup()` | instance | 最後にアクティブだった所有ポップアップ。自身を返す場合もある。 |
| `Window.isVisible()` | instance | 可視状態のbool。 |
| `Window.isEnabled()` | instance | 入力可能状態のbool。 |
| `Window.isMinimized()` | instance | 最小化状態のbool。 |
| `Window.isMaximized()` | instance | 最大化状態のbool。 |
| `Window.minimize()` | instance | SC_MINIMIZEを同期送信。結果0ならNone、それ以外はOSError。 |
| `Window.maximize()` | instance | SC_MAXIMIZEを同期送信。結果0ならNone、それ以外はOSError。 |
| `Window.restore()` | instance | SC_RESTOREを同期送信。結果0ならNone、それ以外はOSError。 |
| `Window.getCheck()` | instance | BM_GETCHECKの状態を0/1/2で返す。チェックボックス等の対象へ使う。 |
| `Window.setCheck(state)` | instance | BM_SETCHECKへ0/1/2を送信。Noneを返す。他の値はValueError。 |
| `Window.postMessage(msg, wparam=0, lparam=0)` | instance | 非同期送信。全引数はC int。成功None、失敗OSError。 |
| `Window.sendMessage(msg, wparam=0, lparam=0)` | instance | 同期送信し結果をC intで返す。64bitポインターを引数/結果として渡せない。対象が応答しないと待機する。 |
| `Window.setForeground(force=0)` | instance | 前面化を要求。成功None、取得できたWin32エラーはOSError。forceは別スレッドの場合に入力スレッド接続を試し、タイムアウト取得成功時だけ一時的に0へ設定する。設定成功時だけ元値の復元を試す。補助APIの失敗はログに出し、前面化や全状態の復元を保証しない。 |
| `Window.getForeground()` | static | 現在の前面窓またはNone。 |
| `Window.setActive()` | instance | SetActiveWindowを呼びNone。前面化やキーボードフォーカスの取得を保証しない。 |
| `Window.getFocus()` | static | 前面スレッドのフォーカス窓またはNone。GetGUIThreadInfo失敗はOSError。 |
| `Window.getCaret()` | static | (キャレット所有WindowまたはNone, (left, top, right, bottom))。矩形はその窓のクライアントピクセル。失敗OSError。 |
| `Window.find(class_name, title)` | static | クラス名/タイトルの完全一致でトップレベル窓を検索しWindowまたはNone。None等の非strは条件なし。 |
| `Window.enum(callback, arg)` | static | トップレベル窓ごとにcallback(window, arg)。C intの非0で継続、0で停止。Noneを返す。callback例外・不正な戻り値・引数構築失敗は表示して列挙停止。 |
| `Window.getDesktop()` | static | デスクトップ窓のWindowを返す。 |
| `Window.fromHWND(hwnd)` | static | 符号なしポインター幅整数をラップ。0はNone、負数/過大値はOverflowError。不正型はTypeError。 |
| `Window.getMonitorInfo()` | static | [[モニター矩形リスト, 作業領域矩形リスト, flags], ...]。矩形は画面ピクセル、flagsの1が主画面。 |
| `Window.getImage()` | instance | 枠を含む窓画像をRGBのImageで取得。寸法が非正なら0×0画像。不可視/遮蔽/最小化/独自描画の内容取得を保証しない。 |
| `Window.getImeStatus()` | instance | 既定IME窓のopen状態をboolで取得。変換中判定ではない。 |
| `Window.isImeConverting(timeout=1000)` | instance | 別プロセスの指定HWNDの変換状態をbool、非対応をNoneで返す。@ref pyauto_ime_composition の対象・待機上限・失敗契約を参照。 |
| `Window.setImeStatus(open)` | instance | C intの0/非0でIMEを閉じる/開く。Noneを返すが、任意のIMEでの反映は保証しない。 |

@subsection pyauto_ime_composition IME変換状態
isImeConvertingは指定HWNDのUI Automation要素の子孫から、HasKeyboardFocus=Trueの最初の要素を選び、TextEditPatternを別MTAスレッドで照会します。
独自HWNDを持たないブラウザー内の編集要素も対象です。フォーカス要素がなければ指定HWND自身を照会し、別の窓へ探索を広げません。
選択したフォーカス要素が非対応または照会失敗の場合、親要素のFalseで置き換えません。探索はUIAのcontrol view内に限ります。
Windows 8.1以降で、対象の公開プロバイダーがGetActiveCompositionに対応する場合だけ利用できます。
未確定の入力・変換候補を含むactive compositionの有無であり、IMEの開閉・候補窓の表示とは別です。
Trueは空でない変換範囲あり、Falseは対応プロバイダーが範囲なし、または端点の一致する空範囲を返した場合、NoneはTextEditPattern/操作/OSクラスが非対応の場合です。
IMM/TSFを直接照会する代替や独自DLL注入・入力監視はありません。UIAを公開しない編集欄や、フォーカスされていないwindowless要素を個別指定する用途には対応しません。
EdgeのHTML textareaでwindowlessな編集要素の選択と非変換時のFalseを確認しています。実IMEの状態遷移や任意のアプリ/IMEへの対応を保証するものではありません。
同一プロセスはValueError、無効HWNDはOSError（winerror=1400）、COM/権限等の照会失敗はHRESULT付きOSErrorです。管理者窓・保護されたデスクトップへのアクセスは保証しません。
timeoutは位置引数のC int、1～60000ミリ秒、既定1000です。接続/通信にも同じ上限を設定し、呼出し側のイベント待機をこの時間で打ち切ります（OSスケジューリング遅延は除く）。
期限切れはTimeoutErrorであり、FalseやNoneへ置き換えません。後始末はワーカーが行い、終了までは次の照会をOSError（winerror=170）で拒否します。
プロセス内の同時照会は1件だけです。応答が戻らなければ以後もbusyとなり、必要なら呼出し元を再起動します。強制終了やスレッドの追加蓄積はしません。
結果は照会時点のスナップショットです。UI/フックで繰返し同期照会せず、ワーカーから呼びます。getFocus()で外部の編集欄を含むHWNDを選べますが、OSのフォーカス変更・HWND再使用は別に扱ってください。

@section pyauto_Image Image
Window.getImageまたはImage.fromStringから取得し、Image()を直接構築しません。コピーしたバッファを所有し、参照解放で破棄します。
寸法はC intで受け取り、正の寸法のRGBバイト数を乗算前に検査します。Py_ssize_tの上限超過はOverflowError、確保失敗はMemoryErrorです。
幅または高さが非正なら0×0画像（バッファは空bytes）になります。負寸法の旧符号変換による偶発的なバッファ長制限は適用しません。空画像はfindで(0, 0)に一致します。
getImageは矩形・DC・ビットマップ・コピー・取得データの失敗をRuntimeErrorにし、GetBitmapBitsのバイト数が符号付きLONGの上限を超える場合はOverflowErrorにします。失敗時も取得済み資源を解放し、選択状態の復元後にDC・ビットマップを破棄します。復元失敗時もDCを先に破棄します。
findは上から下・左から右へ走査します。拡縮・透過・許容誤差・PIL依存はありません。

| 呼出し（self省略） | 種別 | 契約 |
|---|---|---|
| `Image.getSize()` | instance | (width, height)のピクセル整数タプル。 |
| `Image.getMode()` | instance | 文字列RGBを返す。 |
| `Image.getBuffer()` | instance | 上から行順、各画素R/G/Bのbytesコピーを返す。パディングなし。 |
| `Image.fromString(mode, size, data)` | static | modeはRGBのみ、sizeは(width, height)、dataはbytes。先頭width*height*3バイトをコピーし余剰は無視。不足/非RGBはValueError。 |
| `Image.find(needle)` | instance | 別のImageを完全一致で検索し最初の(x, y)、未発見はNone。不正型はTypeError。 |

@section pyauto_Input Input
Input()は空のイベント容器です。set*は追加でなく内容を置換してNoneを返し、まだ入力は送信しません。
キーはWindows仮想キー、文字はUTF-16の1単位です。補助平面文字では明示的にサロゲート単位を準備する必要があります。
マウス座標はC intの画面ピクセルです。仮想デスクトップの原点・寸法で正規化しMOUSEEVENTF_VIRTUALDESKを付けるため、左/上の画面の負座標も使えます。仮想画面外は各軸の端へ丸めます。
ボタン操作は移動も含み、ホイール操作は移動しません。
sendは指定WindowでなくOSの入力列/アクティブアプリを対象にします。同期で投入しますが、対象アプリの処理完了を待つ意味ではありません。
極端に大きいバッチを作らず、キー/ボタンのDown/Upを対応させてください。エラーでも既送信の入力は戻りません。
setKeyboardStateはネイティブのs#が受けるbytesまたはUTF-8化したstrで、結果が正確に256バイト必要です。往復にはgetKeyboardStateのbytesを使います。

| 呼出し（self省略） | 種別 | 契約 |
|---|---|---|
| `Input.setKeyDown(vk)` | instance | 仮想キー押下1イベント。vkはC int。WORDへ変換するため有効なWindows仮想キーを使う。 |
| `Input.setKeyUp(vk)` | instance | 仮想キー解放1イベント。vkはC int。WORDへ変換するため有効なWindows仮想キーを使う。 |
| `Input.setKey(vk)` | instance | 仮想キー押下→解放の2イベント。vkはC int。WORDへ変換するため有効なWindows仮想キーを使う。 |
| `Input.setChar(code)` | instance | UTF-16の1単位を押下/解放へ設定。C intを16bitへ切詰め、補助平面文字のサロゲート対は自動生成しない。 |
| `Input.setMouseMove(x, y)` | instance | 仮想デスクトップの画面ピクセル位置への絶対移動。 |
| `Input.setMouseLeftDown(x, y)` | instance | 仮想デスクトップの画面ピクセル位置へ移動して左ボタン押下。 |
| `Input.setMouseLeftUp(x, y)` | instance | 仮想デスクトップの画面ピクセル位置へ移動して左ボタン解放。 |
| `Input.setMouseLeftClick(x, y)` | instance | 仮想デスクトップの画面ピクセル位置へ移動して左ボタン押下→解放。 |
| `Input.setMouseRightDown(x, y)` | instance | 仮想デスクトップの画面ピクセル位置へ移動して右ボタン押下。 |
| `Input.setMouseRightUp(x, y)` | instance | 仮想デスクトップの画面ピクセル位置へ移動して右ボタン解放。 |
| `Input.setMouseRightClick(x, y)` | instance | 仮想デスクトップの画面ピクセル位置へ移動して右ボタン押下→解放。 |
| `Input.setMouseMiddleDown(x, y)` | instance | 仮想デスクトップの画面ピクセル位置へ移動して中ボタン押下。 |
| `Input.setMouseMiddleUp(x, y)` | instance | 仮想デスクトップの画面ピクセル位置へ移動して中ボタン解放。 |
| `Input.setMouseMiddleClick(x, y)` | instance | 仮想デスクトップの画面ピクセル位置へ移動して中ボタン押下→解放。 |
| `Input.setMouseWheel(x, y, wheel)` | instance | 垂直（正は上）ホイール。wheelはfloatで1.0が120単位。x/yを保持するがMOVEフラグがなく、ポインターは移動しない。 |
| `Input.setMouseHorizontalWheel(x, y, wheel)` | instance | 水平（正は右）ホイール。wheelはfloatで1.0が120単位。x/yを保持するがMOVEフラグがなく、ポインターは移動しない。 |
| `Input.send(items)` | static | Input派生インスタンスのlist/tupleを順番にSendInputへ一括送信。成功None、部分送信を含む失敗はOSError。部分送信は巻戻さない。不正コンテナー/要素はTypeError。長さ・要素取得の例外は伝播し、検証失敗時は送信しない。 |
| `Input.getCursorPos()` | static | 現在のポインター位置(x, y)を画面ピクセルで取得。 |
| `Input.getKeyboardState()` | static | 呼出しスレッドの256バイトキー状態をbytesで取得。取得失敗はOSError。 |
| `Input.setKeyboardState(state)` | static | 呼出しスレッドの256バイト状態を設定しNone。長さ不一致はValueError、OS失敗はOSError。物理キー状態の送信ではない。 |
| `Input.getKeyState(vk)` | static | GetKeyStateの生の16bit値を非負整数で返す。押下は0x8000とのビット積で判定。 |
| `Input.getAsyncKeyState(vk)` | static | GetAsyncKeyStateの生の16bit値を非負整数で返す。押下は0x8000とのビット積で判定。 |

@section pyauto_Hook Hook
Hook()は受信用の窓を作り、全コールバックをNoneにします。プロセス全体で有効なHookは1個です。所有者が参照を保持します。有効なHookがある間の追加構築・再初期化はValueError、受信窓の構築失敗はOSErrorです。
構築スレッドのメッセージループで配送し、コールバックも同じスレッドで同期実行します。Noneで配送を無効化し、関数は参照で保持します。
キー/移動/ボタン/ホイールはNoneまたはC intの0で通過、非0のC intで消費します。例外・不正な結果は表示して通過します。
クリップボード関数の戻り値は無視します。コールバックをブロックせず、クリップボードの再入通知は抑止される点に注意します。
このモジュール自身が投入したマウス入力は配送しません。キー入力の除外はvkCode非0も条件です。他の全合成入力を除外する意味ではありません。
キー/マウス属性をNoneにするだけではOSフックを解除しません。終了時はdestroy()だけでキー/マウス/クリップボード監視・受信窓・9属性の保持参照を解放します。
destroy()は繰返し呼べます。破棄後は属性がNoneになり、コールバックの再設定とreset()はValueErrorです。旧Hookの終了・参照解放は新しい所有者へ影響しません。構築・設定・reset・destroyは同じスレッドで行います。
resetはコールバックがなくてもクリップボード監視を開始します。フック登録失敗は一律に例外化されずログになるため、属性設定だけで登録成功とは判断できません。

| 呼出し（self省略） | 種別 | 契約 |
|---|---|---|
| `Hook.destroy()` | instance | 全監視・受信窓・9属性の保持参照を解放しNone。繰返し可。 |
| `Hook.reset()` | instance | 全フックを解除後、設定済みキー/マウスを再登録し、クリップボード監視はコールバックなしでも登録する。None。 |

| 属性・引数 | 契約 |
|---|---|
| `keydown(vk, scan)` | 仮想キーと走査コード。 |
| `keyup(vk, scan)` | 仮想キーと走査コード。 |
| `mousedown(x, y, button)` | 画面ピクセルとVK_LBUTTON/RBUTTON/MBUTTON。 |
| `mouseup(x, y, button)` | 画面ピクセルとボタン仮想キー。 |
| `mousedblclk(x, y, button)` | 画面ピクセルとボタン仮想キー。対象イベントの配送時に呼ぶ。 |
| `mousemove(x, y)` | 仮想デスクトップの画面ピクセル。負座標を含む。 |
| `mousewheel(x, y, wheel)` | 画面ピクセルと120単位で割ったfloat（正は上）。 |
| `mousehorizontalwheel(x, y, wheel)` | 画面ピクセルと120単位で割ったfloat（正は右）。 |
| `clipboard()` | クリップボード変更通知。引数なし。 |

@code{.py}
def release_hook(hook):
    hook.destroy()
@endcode

@section pyauto_module モジュール関数
shellExecuteの任意文字列はstr/Noneを使います。非strは変換・検証せずNULL扱いになるため、暗黙の文字列化を期待しません。fileには空でないパス/URL文字列を渡します。
プロセス終了待ち・プロセスハンドル返却・paramの引用整形は行いません。動的引数には必要に応じてckit.joinArgsを使います。
SEE_MASK_INVOKEIDLIST・SEE_MASK_FLAG_NO_UI・SEE_MASK_NOASYNCを指定し、メッセージループのないワーカースレッドでもShellの起動操作の完了まで待ちます。起動したアプリの終了は待ちません。UAC確認は抑止しません。

| 呼出し（self省略） | 種別 | 契約 |
|---|---|---|
| `pyauto.shellExecute(verb, file, param=None, directory=None, swmode=None)` | static | ShellExecuteExへ委譲しNone。verbはopen/runas等またはNone、fileはパス/URL、paramは整形済み引数文字列、directoryは作業フォルダー。swmodeはNone/空文字列/normal/minimized/maximized。他の文字列はValueError、Shell失敗はOSError。 |
| `pyauto.messageLoop()` | static | このスレッドのメッセージを配送しWM_QUITでNone。停止関数は公開されていない。本体内では既存のUIループを使う。 |
| `pyauto.setDebug(enabled)` | static | C intの0/非0でpyautoの診断出力を切替え、None。本体の設定とは別。 |

@endcond
*/

/**
@cond english
@page pyauto_native Native pyauto APIs

Current native contracts exposed by import pyauto; see @ref pyautoinput for input convenience classes and @ref pyautoconst for integer constants.
Tables omit self and prefix instance operations with the type (call them as target.getText(), etc.). Static operations are called on the type.
Native functions/methods accept positional arguments only. Keep integers within the documented widths and exclude NUL from strings (except length-delimited Input.setKeyboardState). Embedded NUL in string arguments or Hook attribute names raises ValueError.
Except for the isImeConverting query worker, OS operations execute synchronously on the calling thread; keep blocking message/Shell calls out of UI events and hooks.
Prefer MainWindow.ShellExecuteCommand and existing keymaps for ordinary launcher extensions.
Error is an exported exception type, but the failures documented here are not all instances of pyauto.Error.


@section pyauto_Window Window
Obtain instances through fromHWND/find/getForeground/etc., rather than Window(). The wrapper does not own or destroy the OS window.
Zero handles map to None. Instances with a zero handle raise ValueError for instance operations; a nonzero handle is not validated for continued OS lifetime.
Retained wrappers for the same handle are reused; an OS-destroyed/reused handle can become stale. Drop references when no longer needed.
getCaret and enum do not retain wrappers after their results or callback arguments are released.
Unchecked OS queries do not uniformly raise exceptions on failure; do not treat this interface as lifetime validation.
setRect uses screen coordinates for top-level windows, but parent-client coordinates for child windows.
enum callbacks run synchronously on the caller, must return a C int (not None), and should finish quickly.

| Call (self omitted) | Kind | Contract |
|---|---|---|
| `Window.getText()` | instance | Return title as str. |
| `Window.getClassName()` | instance | Return window class name as str, up to 255 UTF-16 code units; an empty string on Win32 retrieval failure. |
| `Window.getProcessName()` | instance | Return process executable basename as str; snapshot failure raises OSError. |
| `Window.getProcessPath()` | instance | Return process executable path as str; access/enumeration failures raise OSError. |
| `Window.getHWND()` | instance | Return retained HWND as a pointer-width integer. |
| `Window.getRect()` | instance | Return screen-pixel (left, top, right, bottom), right/bottom exclusive. |
| `Window.setRect(rect)` | instance | Move/resize with four integers; None on success, OSError on MoveWindow failure. Child windows use parent-client coordinates. |
| `Window.getClientRect()` | instance | Return client-pixel (left, top, right, bottom). |
| `Window.clientToScreen(x, y)` | instance | Convert client pixels to screen-pixel (x, y). |
| `Window.getFirstChild()` | instance | Return first child or None. |
| `Window.getLastChild()` | instance | Return last child or None. |
| `Window.getPrevious()` | instance | Return previous window in Z order or None. |
| `Window.getNext()` | instance | Return next window in Z order or None. |
| `Window.getParent()` | instance | Return GA_PARENT parent or None. |
| `Window.getOwner()` | instance | Return owner or None, independently of parent/child relationship. |
| `Window.getLastActivePopup()` | instance | Return last active owned popup; may return self. |
| `Window.isVisible()` | instance | Return visibility bool. |
| `Window.isEnabled()` | instance | Return enabled-state bool. |
| `Window.isMinimized()` | instance | Return minimized-state bool. |
| `Window.isMaximized()` | instance | Return maximized-state bool. |
| `Window.minimize()` | instance | Synchronously send SC_MINIMIZE; return None for zero result, otherwise raise OSError. |
| `Window.maximize()` | instance | Synchronously send SC_MAXIMIZE; return None for zero result, otherwise raise OSError. |
| `Window.restore()` | instance | Synchronously send SC_RESTORE; return None for zero result, otherwise raise OSError. |
| `Window.getCheck()` | instance | Return BM_GETCHECK state as 0/1/2; use with an appropriate control. |
| `Window.setCheck(state)` | instance | Send BM_SETCHECK state 0/1/2 and return None; other values raise ValueError. |
| `Window.postMessage(msg, wparam=0, lparam=0)` | instance | Post asynchronously; all arguments are C int. Return None on success, OSError on failure. |
| `Window.sendMessage(msg, wparam=0, lparam=0)` | instance | Send synchronously and return C int; arguments/results cannot carry 64-bit pointers. Can block on an unresponsive target. |
| `Window.setForeground(force=0)` | instance | Request foreground activation; return None or OSError for a reported Win32 error. For different threads, force attempts input-thread attachment and temporarily sets the timeout to zero only after a successful query. It attempts restoration only after a successful change. Auxiliary API failures are logged; activation and restoration of every state are not guaranteed. |
| `Window.getForeground()` | static | Return foreground window or None. |
| `Window.setActive()` | instance | Call SetActiveWindow and return None without guaranteeing foreground or keyboard focus. |
| `Window.getFocus()` | static | Return foreground-thread focus window or None; GetGUIThreadInfo failure raises OSError. |
| `Window.getCaret()` | static | Return (caret Window or None, (left, top, right, bottom)) in that window's client pixels; failure raises OSError. |
| `Window.find(class_name, title)` | static | Find a top-level window by exact class/title, returning Window or None. Non-str values including None omit that condition. |
| `Window.enum(callback, arg)` | static | Call callback(window, arg) per top-level window: nonzero C int continues, zero stops. Return None; print callback exceptions, invalid results or argument construction failures and stop enumeration. |
| `Window.getDesktop()` | static | Return the desktop Window. |
| `Window.fromHWND(hwnd)` | static | Wrap an unsigned pointer-width integer; zero returns None, negative/oversized values raise OverflowError, invalid types TypeError. |
| `Window.getMonitorInfo()` | static | Return [[monitor_rect_list, work_rect_list, flags], ...] in screen pixels; flag bit 1 identifies the primary display. |
| `Window.getImage()` | instance | Capture the window including its frame as an RGB Image; nonpositive dimensions produce an empty image. Contents are not guaranteed for hidden/occluded/minimized/custom-rendered windows. |
| `Window.getImeStatus()` | instance | Return default IME-window open status as bool, not composition state. |
| `Window.isImeConverting(timeout=1000)` | instance | Return bool composition state for this foreign HWND, or None for unsupported providers; see @ref pyauto_ime_composition for target/deadline/failure contracts. |
| `Window.setImeStatus(open)` | instance | Close/open IME with zero/nonzero C int; return None without guaranteeing support by every IME. |

@subsection pyauto_ime_composition IME composition
isImeConverting selects the first UIA element with HasKeyboardFocus=True among descendants of the supplied HWND's UIA element, then queries TextEditPattern on a separate MTA thread.
This includes browser edit elements without their own HWND. If no focused element is found, it queries the supplied HWND itself; it never searches another window.
An unsupported or failed focused-element query never falls back to a parent's False. Discovery is limited to the UIA control view.
It requires Windows 8.1 or later and an exposed provider implementing GetActiveComposition.
Active composition includes uncommitted input/conversion; it differs from IME open status and candidate-window visibility.
True means a nonempty active range, False means a supported provider returned no range or a range with equal endpoints, and None means the pattern/operation/OS class is unsupported.
There is no direct IMM/TSF fallback, custom DLL injection, or input monitoring. Editors without a suitable UIA provider and individually selecting an unfocused windowless element are unsupported.
An HTML textarea in Edge has been checked for windowless edit selection and False when idle. This does not establish real IME transitions or support for every application/IME.
Same-process targets raise ValueError, invalid HWNDs raise OSError (winerror=1400), and COM/access/query failures raise OSError with the HRESULT. Access to elevated windows or protected desktops is not guaranteed.
timeout is a positional C int in 1..60000 milliseconds, default 1000. It also sets connection/transaction limits; the caller stops waiting for completion at this deadline, excluding OS scheduling delays.
TimeoutError never becomes False or None. The worker finishes cleanup; until it exits, further queries raise OSError (winerror=170).
Only one query may be in flight per process. A provider that never returns keeps this API busy; restart the caller if needed. Threads are neither forcibly terminated nor accumulated.
Results are snapshots. Call from a worker rather than repeatedly blocking UI/hook callbacks. getFocus() can select a HWND containing an external edit field; focus changes and OS handle reuse remain the caller's concern.

@section pyauto_Image Image
Obtain images from Window.getImage or Image.fromString, not Image(). Image owns its copied buffer and releases it when Python references are gone.
Dimensions are parsed as C int. Positive RGB byte counts are checked before multiplication; exceeding Py_ssize_t raises OverflowError and allocation failure raises MemoryError.
A nonpositive width or height produces a 0 by 0 image with an empty bytes buffer. The accidental buffer-length restriction from the old signed-to-unsigned conversion of negative dimensions is not applied. An empty needle matches at (0, 0).
getImage raises RuntimeError for rectangle, DC, bitmap, copy or data retrieval failures, and OverflowError when the GetBitmapBits byte count exceeds signed LONG. Acquired resources are released on failure; the original selection is restored before destroying the DC and bitmap. The DC is destroyed first even if restoration fails.
find scans rows from top to bottom and columns from left to right; no scaling, alpha, tolerance or PIL dependency is provided.

| Call (self omitted) | Kind | Contract |
|---|---|---|
| `Image.getSize()` | instance | Return pixel-size integer tuple (width, height). |
| `Image.getMode()` | instance | Return the string RGB. |
| `Image.getBuffer()` | instance | Return copied bytes in top-to-bottom row order, R/G/B per pixel, without padding. |
| `Image.fromString(mode, size, data)` | static | mode must be RGB; size is (width, height), data is bytes. Copy the first width*height*3 bytes and ignore trailing bytes; insufficient data/non-RGB raises ValueError. |
| `Image.find(needle)` | instance | Find another Image by exact pixels; return first (x, y), or None. Invalid type raises TypeError. |

@section pyauto_Input Input
Input() creates an empty event container. set* replaces its contents rather than appending, returns None, and does not send input.
Key codes are Windows virtual keys; character codes are single UTF-16 units. Supplementary characters require explicitly prepared surrogate units.
Mouse positions are C-int screen pixels. Normalization uses the virtual desktop origin and dimensions with MOUSEEVENTF_VIRTUALDESK, including negative coordinates on displays to the left/above. Coordinates outside the virtual bounds are clamped on each axis.
Mouse button operations also move; wheel operations do not.
send targets the OS input stream/active application, not a supplied Window. It is synchronous submission, not confirmation that an application processed events.
Keep batches reasonably small. Explicitly pair key/button down and up; already-sent events are not undone by an error.
setKeyboardState accepts the native s# input forms (bytes or a str encoded as UTF-8), requiring exactly 256 resulting bytes. Use getKeyboardState bytes for round trips.

| Call (self omitted) | Kind | Contract |
|---|---|---|
| `Input.setKeyDown(vk)` | instance | One virtual-key down event. vk is C int converted to WORD; use a valid Windows virtual key. |
| `Input.setKeyUp(vk)` | instance | One virtual-key up event. vk is C int converted to WORD; use a valid Windows virtual key. |
| `Input.setKey(vk)` | instance | Virtual-key down/up pair. vk is C int converted to WORD; use a valid Windows virtual key. |
| `Input.setChar(code)` | instance | Set down/up events for one UTF-16 unit; truncate C int to 16 bits without synthesizing surrogate pairs. |
| `Input.setMouseMove(x, y)` | instance | Absolute movement to virtual-desktop screen pixel coordinates. |
| `Input.setMouseLeftDown(x, y)` | instance | Move to virtual-desktop screen pixels and issue left button down. |
| `Input.setMouseLeftUp(x, y)` | instance | Move to virtual-desktop screen pixels and issue left button up. |
| `Input.setMouseLeftClick(x, y)` | instance | Move to virtual-desktop screen pixels and issue left button down/up. |
| `Input.setMouseRightDown(x, y)` | instance | Move to virtual-desktop screen pixels and issue right button down. |
| `Input.setMouseRightUp(x, y)` | instance | Move to virtual-desktop screen pixels and issue right button up. |
| `Input.setMouseRightClick(x, y)` | instance | Move to virtual-desktop screen pixels and issue right button down/up. |
| `Input.setMouseMiddleDown(x, y)` | instance | Move to virtual-desktop screen pixels and issue middle button down. |
| `Input.setMouseMiddleUp(x, y)` | instance | Move to virtual-desktop screen pixels and issue middle button up. |
| `Input.setMouseMiddleClick(x, y)` | instance | Move to virtual-desktop screen pixels and issue middle button down/up. |
| `Input.setMouseWheel(x, y, wheel)` | instance | Set vertical (positive upward) wheel; float wheel=1.0 means 120 units. Store x/y without a MOVE flag, so do not move the pointer. |
| `Input.setMouseHorizontalWheel(x, y, wheel)` | instance | Set horizontal (positive rightward) wheel; float wheel=1.0 means 120 units. Store x/y without a MOVE flag, so do not move the pointer. |
| `Input.send(items)` | static | Submit a list/tuple of Input instances/subclasses in order through SendInput; success returns None. Failed/partial submission raises OSError without rollback; invalid container/elements raise TypeError. Length/item retrieval exceptions propagate; validation failure sends nothing. |
| `Input.getCursorPos()` | static | Return pointer screen-pixel (x, y). |
| `Input.getKeyboardState()` | static | Return this thread's 256-byte keyboard state as bytes; failure raises OSError. |
| `Input.setKeyboardState(state)` | static | Set this thread's 256-byte state and return None; wrong length raises ValueError, OS failure OSError. Do not inject physical key events. |
| `Input.getKeyState(vk)` | static | Return the raw unsigned 16-bit GetKeyState value; test pressed state with bit mask 0x8000. |
| `Input.getAsyncKeyState(vk)` | static | Return the raw unsigned 16-bit GetAsyncKeyState value; test pressed state with bit mask 0x8000. |

@section pyauto_Hook Hook
Hook() creates a receiver window and initializes callbacks to None. Retain one owner for the process-global active Hook. Construction or reinitialization while a Hook is active raises ValueError; receiver-window creation failure raises OSError.
Use the construction thread's message loop; callbacks execute there synchronously. None disables a callback; callbacks are retained by reference.
Keyboard/move/button/wheel callbacks return None or C int zero to pass through, nonzero C int to consume. Exceptions/invalid results are printed and pass through.
Clipboard callback returns are ignored. Do not block in callbacks; recursive clipboard notifications are suppressed.
Events injected by this module bypass mouse callbacks; keyboard bypass also requires nonzero vkCode. This is not a general filter for all injected input.
Assigning keyboard/mouse callbacks to None does not itself uninstall their OS hooks. For teardown, destroy() alone releases keyboard/mouse/clipboard monitoring, the receiver window and references in all nine callback attributes.
destroy() is repeatable. Attributes read as None after destruction; callback assignment and reset() then raise ValueError. Releasing an old Hook does not affect a new owner. Construct, configure, reset and destroy on the same thread.
reset always starts clipboard listening, even without a clipboard callback. Hook installation errors are logged rather than consistently raised, so callback assignment does not prove installation succeeded.

| Call (self omitted) | Kind | Contract |
|---|---|---|
| `Hook.destroy()` | instance | Release all monitoring, the receiver window and all nine callback references; return None. Repeatable. |
| `Hook.reset()` | instance | Uninstall all hooks, reinstall configured keyboard/mouse callbacks and always start clipboard monitoring, even without a callback. Return None. |

| Attribute/arguments | Contract |
|---|---|
| `keydown(vk, scan)` | Virtual key and scan code. |
| `keyup(vk, scan)` | Virtual key and scan code. |
| `mousedown(x, y, button)` | Screen pixels and VK_LBUTTON/RBUTTON/MBUTTON. |
| `mouseup(x, y, button)` | Screen pixels and button virtual key. |
| `mousedblclk(x, y, button)` | Screen pixels and button virtual key; called when that event is delivered. |
| `mousemove(x, y)` | Virtual-desktop screen pixels, including negative coordinates. |
| `mousewheel(x, y, wheel)` | Screen pixels and float delta divided by 120 (positive up). |
| `mousehorizontalwheel(x, y, wheel)` | Screen pixels and float delta divided by 120 (positive right). |
| `clipboard()` | Clipboard change notification with no arguments. |

@code{.py}
def release_hook(hook):
    hook.destroy()
@endcode

@section pyauto_module Module functions
shellExecute accepts str/None for optional text. Other non-str objects are treated as NULL rather than validated as text; do not rely on coercion. file should be a nonempty path/URL string.
It does not wait for process exit, return a process handle, or quote param for you. Use ckit.joinArgs to prepare dynamic arguments where appropriate.
SEE_MASK_INVOKEIDLIST, SEE_MASK_FLAG_NO_UI, and SEE_MASK_NOASYNC wait for the Shell launch operation even on a worker without a message loop. They do not wait for the launched application's exit or suppress UAC prompts.

| Call (self omitted) | Kind | Contract |
|---|---|---|
| `pyauto.shellExecute(verb, file, param=None, directory=None, swmode=None)` | static | Call ShellExecuteEx and return None. verb is open/runas/etc. or None; file is a path/URL, param a prepared argument string, directory the working folder. swmode accepts None/empty/normal/minimized/maximized; other strings raise ValueError and Shell failure raises OSError. |
| `pyauto.messageLoop()` | static | Dispatch this thread's messages until WM_QUIT, then return None. No stop function is exposed; use the existing UI loop inside the application. |
| `pyauto.setDebug(enabled)` | static | Toggle pyauto diagnostics with zero/nonzero C int and return None, independently of application settings. |

@endcond
*/

static PyMethodDef pyauto_funcs[] = {
	{"shellExecute", _shellExecute, METH_VARARGS, ""},
	{"messageLoop", _messageLoop, METH_VARARGS, ""},
	{"setDebug", _setDebug, METH_VARARGS, ""},
	{NULL, NULL, 0, NULL}};

// ------------ module init -----------------------------------------

static PyModuleDef pyautocore_module =
	{
		PyModuleDef_HEAD_INIT,
		MODULE_NAME,
		"pyautocore module.",
		-1,
		pyauto_funcs,
		NULL, NULL, NULL, NULL};

PyMODINIT_FUNC PyInit_pyautocore()
{
	if (PyType_Ready(&PyType_Window) < 0)
		return NULL;
	if (PyType_Ready(&PyType_Image) < 0)
		return NULL;
	if (PyType_Ready(&PyType_Input) < 0)
		return NULL;
	if (PyType_Ready(&PyType_Hook) < 0)
		return NULL;

	PyObject *m;

	m = PyModule_Create(&pyautocore_module);
	if (m == NULL)
		return NULL;

	Py_INCREF(&PyType_Window);
	PyModule_AddObject(m, "Window", (PyObject *)&PyType_Window);

	Py_INCREF(&PyType_Image);
	PyModule_AddObject(m, "Image", (PyObject *)&PyType_Image);

	Py_INCREF(&PyType_Input);
	PyModule_AddObject(m, "Input", (PyObject *)&PyType_Input);

	Py_INCREF(&PyType_Hook);
	PyModule_AddObject(m, "Hook", (PyObject *)&PyType_Hook);

	g.Error = PyErr_NewException(MODULE_NAME ".Error", NULL, NULL);
	Py_INCREF(g.Error);
	PyModule_AddObject(m, "Error", (PyObject *)g.Error);

	if (PyErr_Occurred())
	{
		Py_FatalError("can't initialize module " MODULE_NAME);
	}

	return m;
}

// ------------ DllMain -----------------------------------------

BOOL APIENTRY DllMain(HANDLE hModule,
					  DWORD ul_reason_for_call,
					  LPVOID lpReserved)
{
	(void)lpReserved;
	if (ul_reason_for_call == DLL_PROCESS_ATTACH)
	{
		g.module_handle = (HMODULE)hModule;
	}
	return TRUE;
}
