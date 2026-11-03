#include <stdio.h>

#include <windows.h>

#include "pythonutil.h"
#include "pyautocore.h"

static HHOOK key_hook = NULL;

using namespace pyauto;

// Interaction between WH_KEYBOARD_LL and SendInput:
//
//   Calling SendInput() inside KeyHookProc() can cause
//   a nested invocation of KeyHookProc().
//
LRESULT CALLBACK KeyHookProc(int nCode, WPARAM wParam, LPARAM lParam)
{
	PythonUtil::GIL_Ensure gil_ensure;

	if (nCode < 0 || !g.pyhook)
	{
		LRESULT result = CallNextHookEx(key_hook, nCode, wParam, lParam);
		return result;
	}

	KBDLLHOOKSTRUCT *pkbdllhook = (KBDLLHOOKSTRUCT *)lParam;

	// Report an unexpected timestamp inversion.
	if (g.last_key_time > pkbdllhook->time)
	{
		PythonUtil_Printf("Time stamp inversion happened.\n");
	}

	// Do not pass key events injected by this module's SendInput to Python callbacks.
	// Events with vkCode == 0 bypass this filter and continue to Python handling.
	if (pkbdllhook->flags & LLKHF_INJECTED && pkbdllhook->dwExtraInfo == (ULONG_PTR)g.module_handle && pkbdllhook->vkCode)
	{
		LRESULT result = CallNextHookEx(key_hook, nCode, wParam, lParam);
		return result;
	}

	switch (wParam)
	{
	case WM_KEYDOWN:
	case WM_SYSKEYDOWN:
		if (g.pyhook->keydown)
		{
			DWORD vk = pkbdllhook->vkCode;
			DWORD scan = pkbdllhook->scanCode;
			g.last_key_time = pkbdllhook->time;

			PyObject *callback = Py_NewRef(g.pyhook->keydown);
			PyObject *pyarglist = Py_BuildValue("(ii)", vk, scan);
			PyObject *pyresult = PyObject_Call(callback, pyarglist, NULL);
			Py_DECREF(callback);
			Py_DECREF(pyarglist);
			if (pyresult)
			{
				int result = 0;
				if (pyresult == Py_None)
				{
					result = 0;
				}
				else if (!PyArg_Parse(pyresult, "i", &result))
				{
					PyErr_Print();
					result = 0;
				}
				Py_DECREF(pyresult);

				if (result)
				{
					return result;
				}
			}
			else
			{
				PyErr_Print();
			}
		}
		break;

	case WM_KEYUP:
	case WM_SYSKEYUP:
		if (g.pyhook->keyup)
		{
			DWORD vk = pkbdllhook->vkCode;
			DWORD scan = pkbdllhook->scanCode;
			g.last_key_time = pkbdllhook->time;

			PyObject *callback = Py_NewRef(g.pyhook->keyup);
			PyObject *pyarglist = Py_BuildValue("(ii)", vk, scan);
			PyObject *pyresult = PyObject_Call(callback, pyarglist, NULL);
			Py_DECREF(callback);
			Py_DECREF(pyarglist);
			if (pyresult)
			{
				int result = 0;
				if (pyresult == Py_None)
				{
					result = 0;
				}
				else if (!PyArg_Parse(pyresult, "i", &result))
				{
					PyErr_Print();
					result = 0;
				}
				Py_DECREF(pyresult);

				if (result)
				{
					return result;
				}
			}
			else
			{
				PyErr_Print();
			}
		}
		break;
	}

	LRESULT result = CallNextHookEx(key_hook, nCode, wParam, lParam);
	return result;
}

void HookStart_Key()
{
	if (!key_hook)
	{
		PythonUtil_DebugPrintf("SetWindowsHookEx\n");
		key_hook = SetWindowsHookEx(WH_KEYBOARD_LL, KeyHookProc, g.module_handle, 0);
	}

	if (key_hook == NULL)
	{
		PythonUtil_DebugPrintf("SetWindowsHookEx failed : %x\n", GetLastError());
	}
}

void HookEnd_Key()
{
	if (key_hook)
	{
		if (!UnhookWindowsHookEx(key_hook))
		{
			PythonUtil_DebugPrintf("UnhookWindowsHookEx(key) failed\n");
		}

		key_hook = NULL;
	}
}
