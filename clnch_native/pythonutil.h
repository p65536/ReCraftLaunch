#ifndef _PYTHONUTIL_H_
#define _PYTHONUTIL_H_

#include <string>

#if defined(_DEBUG)
#undef _DEBUG
#include "python.h"
#define _DEBUG
#else
#include "python.h"
#endif

namespace PythonUtil
{
	// Reject embedded NUL with ValueError; return false with the Python exception set.
	bool PyStringToString(const PyObject *pystr, std::string *str);
	bool PyStringToWideString(const PyObject *pystr, std::wstring *str);

	class GIL_Ensure
	{
	public:
		GIL_Ensure()
		{
			state = PyGILState_Ensure();
		};

		~GIL_Ensure()
		{
			PyGILState_Release(state);
		};

	private:
		PyGILState_STATE state;
	};
};

#endif // _PYTHONUTIL_H_
