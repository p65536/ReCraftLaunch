#include <cwchar>
#include "strutil.h"
#include "pythonutil.h"

bool PythonUtil::PyStringToString(PyObject *pystr, std::string *str)
{
	if (PyUnicode_Check(pystr))
	{
		wchar_t *s = PyUnicode_AsWideCharString(pystr, NULL);
		if (!s)
			return false;

		*str = StringUtil::WideCharToMultiByte(s, (int)std::wcslen(s));
		PyMem_Free(s);
		return true;
	}
	else
	{
		PyErr_SetString(PyExc_TypeError, "must be unicode.");
		*str = "";
		return false;
	}
}

bool PythonUtil::PyStringToWideString(PyObject *pystr, std::wstring *str)
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
		PyErr_SetString(PyExc_TypeError, "must be unicode.");
		*str = L"";
		return false;
	}
}
