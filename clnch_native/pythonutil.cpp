#include <cwchar>
#include "strutil.h"
#include "pythonutil.h"

bool PythonUtil::PyStringToString(const PyObject *pystr, std::string *str)
{
    if (PyUnicode_Check(pystr))
    {
        wchar_t *wide = PyUnicode_AsWideCharString(const_cast<PyObject *>(pystr), NULL);
        if (!wide)
        {
            *str = "";
            return false;
        }

        *str = StringUtil::WideCharToMultiByte(wide, (int)std::wcslen(wide));
        PyMem_Free(wide);
        return true;
    }
    else
    {
        PyErr_SetString(PyExc_TypeError, "must be string or unicode.");
        *str = "";
        return false;
    }
}

bool PythonUtil::PyStringToWideString(const PyObject *pystr, std::wstring *str)
{
    if (PyUnicode_Check(pystr))
    {
        wchar_t *wide = PyUnicode_AsWideCharString(const_cast<PyObject *>(pystr), NULL);
        if (!wide)
        {
            *str = L"";
            return false;
        }

        *str = wide;
        PyMem_Free(wide);
        return true;
    }
    else
    {
        PyErr_SetString(PyExc_TypeError, "must be string or unicode.");
        *str = L"";
        return false;
    }
}
