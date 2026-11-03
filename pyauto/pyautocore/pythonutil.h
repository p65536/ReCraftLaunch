#ifndef _PYTHONUTIL_H_
#define _PYTHONUTIL_H_

#if defined(_DEBUG)
#undef _DEBUG
#include "python.h"
#define _DEBUG
#else
#include "python.h"
#endif

namespace PythonUtil
{

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

#define PythonUtil_Printf(...) PySys_WriteStdout(__VA_ARGS__)
#define PythonUtil_DebugPrintf(...)     \
	if (g.debug)                        \
	{                                   \
		PySys_WriteStdout(__VA_ARGS__); \
	}
};

#endif // _PYTHONUTIL_H_
