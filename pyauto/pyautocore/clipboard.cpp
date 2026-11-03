#include <stdio.h>

#include <windows.h>

#include "pythonutil.h"
#include "pyautocore.h"

using namespace pyauto;

static bool clipboard_hook_installed;

LRESULT Hook_Clipboard_wndProc(HWND hWnd, UINT message, WPARAM wParam, LPARAM lParam)
{
	switch (message)
	{
	case WM_CLIPBOARDUPDATE:
	{
		static bool enter = false;
		if (!enter)
		{
			enter = true;

			if (g.pyhook && g.pyhook->clipboard)
			{
				PyObject *callback = Py_NewRef(g.pyhook->clipboard);
				PyObject *pyarglist = Py_BuildValue("()");
				PyObject *pyresult = PyObject_Call(callback, pyarglist, NULL);
				Py_DECREF(callback);
				Py_DECREF(pyarglist);
				if (pyresult)
				{
					Py_DECREF(pyresult);
				}
				else
				{
					PyErr_Print();
				}
			}

			enter = false;
		}
		else
		{
			PythonUtil_DebugPrintf("WM_CLIPBOARDUPDATE nested!\n");
		}
	}
	break;
	}

	return 0;
}

void HookStart_Clipboard()
{
	if (!clipboard_hook_installed)
	{
		if (AddClipboardFormatListener(g.pyauto_window))
		{
			clipboard_hook_installed = true;
		}
		else
		{
			PythonUtil_DebugPrintf("AddClipboardFormatListener() failed : %x\n", GetLastError());
		}
	}
}

void HookEnd_Clipboard()
{
	if (clipboard_hook_installed)
	{
		clipboard_hook_installed = false;
		if (!RemoveClipboardFormatListener(g.pyauto_window))
		{
			PythonUtil_DebugPrintf("RemoveClipboardFormatListener() failed : %x\n", GetLastError());
		}
	}
}
