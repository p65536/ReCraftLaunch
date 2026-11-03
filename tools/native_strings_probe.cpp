#include <windows.h>
#include <cstdio>
#include <vector>
#include "pythonutil.h"
#include "strutil.h"

static int failures = 0;

static void check(bool condition, const char *label)
{
	if (!condition)
	{
		std::fprintf(stderr, "FAIL: %s\n", label);
		++failures;
	}
}

static std::string encoded(const std::wstring &text)
{
	int length = ::WideCharToMultiByte(CP_ACP, 0, text.data(), (int)text.size(), NULL, 0, NULL, NULL);
	std::string result(length, '\0');
	if (length)
		::WideCharToMultiByte(CP_ACP, 0, text.data(), (int)text.size(), result.data(), length, NULL, NULL);
	return result;
}

static std::wstring decoded(const std::string &text)
{
	int length = ::MultiByteToWideChar(CP_ACP, 0, text.data(), (int)text.size(), NULL, 0);
	std::wstring result(length, L'\0');
	if (length)
		::MultiByteToWideChar(CP_ACP, 0, text.data(), (int)text.size(), result.data(), length);
	return result;
}

static void *fail_malloc(void *, size_t)
{
	return NULL;
}

int main()
{
	// Keep unexpected native failures in the test result, without desktop dialogs.
	SetErrorMode(SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX);
	Py_Initialize();
	const std::vector<std::wstring> good = {L"", L"abc", L"日本語", L"a😀𠀀z"};
	const std::vector<std::wstring> nul = {
		std::wstring(L"\0abc", 4), std::wstring(L"ab\0cd", 5),
		std::wstring(L"abc\0", 4), std::wstring(L"a\0b\0c", 5)};
	for (const auto &text : good)
	{
		PyObject *value = PyUnicode_FromWideChar(text.data(), (Py_ssize_t)text.size());
		std::string result = "sentinel";
		check(PythonUtil::PyStringToString(value, &result), "normal narrow conversion");
		check(result == encoded(text), "unchanged Windows code page conversion");
		check(!PyErr_Occurred(), "normal conversion leaves no exception");
		Py_DECREF(value);
		std::string bytes = encoded(text);
		check(StringUtil::WideCharToMultiByte(text.data(), (int)text.size()) == bytes,
			"normal explicit wide buffer conversion");
		check(StringUtil::MultiByteToWideChar(bytes.data(), (int)bytes.size()) == decoded(bytes),
			"normal explicit multibyte buffer conversion");
	}
	for (const auto &text : nul)
	{
		PyObject *value = PyUnicode_FromWideChar(text.data(), (Py_ssize_t)text.size());
		std::string result;
		check(!PythonUtil::PyStringToString(value, &result), "reject NUL");
		check(PyErr_ExceptionMatches(PyExc_ValueError), "NUL raises ValueError");
		PyErr_Clear();
		Py_DECREF(value);
		// These lower-level functions accept an explicit buffer length.
		std::string bytes = encoded(text);
		check(StringUtil::WideCharToMultiByte(text.data(), (int)text.size()) == bytes,
			"wide-to-multibyte preserves embedded NUL and suffix");
		check(StringUtil::MultiByteToWideChar(bytes.data(), (int)bytes.size()) == text,
			"multibyte-to-wide preserves embedded NUL and suffix");
	}
	PyObject *invalid[] = {Py_NewRef(Py_None), PyLong_FromLong(1), PyBytes_FromString("abc")};
	for (PyObject *value : invalid)
	{
		std::string result = "sentinel";
		check(!PythonUtil::PyStringToString(value, &result), "reject non-str");
		check(PyErr_ExceptionMatches(PyExc_TypeError), "non-str raises TypeError");
		check(result.empty(), "existing non-str output reset");
		PyErr_Clear();
		Py_DECREF(value);
	}
	PyObject *value = PyUnicode_FromString("abc");
	PyMemAllocatorEx original;
	PyMem_GetAllocator(PYMEM_DOMAIN_MEM, &original);
	PyMemAllocatorEx failing = original;
	failing.malloc = fail_malloc;
	std::string result;
	PyMem_SetAllocator(PYMEM_DOMAIN_MEM, &failing);
	bool converted = PythonUtil::PyStringToString(value, &result);
	PyMem_SetAllocator(PYMEM_DOMAIN_MEM, &original);
	check(!converted, "allocation failure returns false");
	check(PyErr_ExceptionMatches(PyExc_MemoryError), "allocation failure propagates MemoryError");
	PyErr_Clear();
	check(PythonUtil::PyStringToString(value, &result) && result == "abc", "recovery after failure");
	Py_DECREF(value);
	check(Py_FinalizeEx() == 0, "Python finalization");
	if (!failures)
		std::printf("Native narrow/string buffer checks OK (ACP=%u)\n", GetACP());
	return failures ? 1 : 0;
}
