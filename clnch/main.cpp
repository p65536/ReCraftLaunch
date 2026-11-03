#include <string>
#include <vector>
#include <list>
#include <new>
#include <stdexcept>

#include <windows.h>
#include <shellapi.h>

#if defined(_DEBUG)
#undef _DEBUG
#include "python.h"
#define _DEBUG
#else
#include "python.h"
#endif

//--------------------------------------

static bool SetupEnvironment(std::wstring &exe_dir)
{
    // Get exe's directory
    {
        std::vector<wchar_t> buffer(MAX_PATH);
        for (;;)
        {
            DWORD length = GetModuleFileNameW(NULL, buffer.data(), (DWORD)buffer.size());
            if (length == 0)
                return false;
            if (length < buffer.size())
            {
                exe_dir.assign(buffer.data(), length);
                break;
            }
            if (buffer.size() == 32768)
                return false;
            buffer.resize((buffer.size() * 2 < 32768) ? buffer.size() * 2 : 32768);
        }

        size_t last_backslash_pos = exe_dir.find_last_of(L"\\/");
        if (last_backslash_pos != std::wstring::npos)
        {
            exe_dir = exe_dir.substr(0, last_backslash_pos);
        }
        else
        {
            exe_dir = L"";
        }
    }

    // Setup environment variable "PATH"
    {
        std::wstring env_path;

        std::vector<wchar_t> buffer;
        for (;;)
        {
            SetLastError(ERROR_SUCCESS);
            DWORD length = GetEnvironmentVariableW(L"PATH", buffer.data(), (DWORD)buffer.size());
            if (length == 0)
            {
                DWORD error = GetLastError();
                if (error != ERROR_SUCCESS && error != ERROR_ENVVAR_NOT_FOUND)
                    return false;
                break;
            }
            if (length < buffer.size())
            {
                env_path.assign(buffer.data(), length);
                break;
            }
            if (length > 32768)
                return false;
            buffer.resize(length);
        }

        env_path = exe_dir + L"/lib;" + env_path;

        if (env_path.size() >= 32767 || !SetEnvironmentVariableW(L"PATH", env_path.c_str()))
            return false;
    }
    return true;
}

int AppMain()
try
{
    std::wstring exe_dir;
    if (!SetupEnvironment(exe_dir))
        return 1;

    // Initialize embedded Python
    {
        PyConfig config;
        PyConfig_InitPythonConfig(&config);

        // Keep source folders free of runtime bytecode caches.
        config.write_bytecode = 0;

        // ReCraftLaunch command-line arguments are not Python options.
        config.parse_argv = 0;

        int argc;
        wchar_t **argv = CommandLineToArgvW(GetCommandLineW(), &argc);
        if (!argv)
        {
            PyConfig_Clear(&config);
            return 1;
        }

        PyStatus status = PyConfig_SetArgv(&config, argc, argv);
        LocalFree(argv);

        if (PyStatus_Exception(status))
        {
            PyConfig_Clear(&config);
            Py_ExitStatusException(status);
        }

#if defined(_DEBUG)
        std::wstring python_home = exe_dir + L"/../../../../Python315/tools";
#else
        std::wstring python_home = exe_dir;
#endif

        status = PyConfig_SetString(&config, &config.home, python_home.c_str());
        if (PyStatus_Exception(status))
        {
            PyConfig_Clear(&config);
            Py_ExitStatusException(status);
        }

        // Explicit module search paths
        config.module_search_paths_set = 1;

        std::vector<std::wstring> python_paths;

        python_paths.push_back(exe_dir);

#if defined(_DEBUG)
        python_paths.push_back(exe_dir + L"/../../../../extensions");
        python_paths.push_back(exe_dir + L"/../../../../clnch");
        python_paths.push_back(exe_dir + L"/../../../..");
        python_paths.push_back(exe_dir + L"/lib");
        python_paths.push_back(python_home + L"/Lib");
        python_paths.push_back(python_home + L"/Lib/site-packages");
        python_paths.push_back(python_home + L"/DLLs");
#else
        python_paths.push_back(exe_dir + L"/extensions");
        python_paths.push_back(exe_dir + L"/library.zip");
        python_paths.push_back(exe_dir + L"/lib");
#endif

        for (const auto &path : python_paths)
        {
            status = PyWideStringList_Append(
                &config.module_search_paths, path.c_str());

            if (PyStatus_Exception(status))
            {
                PyConfig_Clear(&config);
                Py_ExitStatusException(status);
            }
        }

        status = Py_InitializeFromConfig(&config);
        PyConfig_Clear(&config);

        if (PyStatus_Exception(status))
        {
            Py_ExitStatusException(status);
        }
    }

    // enable DPI handling
    SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2);

    // Execute python side main script
    int exit_code = 0;
    {
        PyObject *module = PyImport_ImportModule("clnch_main");
        if (module == NULL)
        {
            exit_code = 1;
            PyErr_Print();
        }

        Py_XDECREF(module);
        module = NULL;
    }

    // Termination
    Py_Finalize();

    return exit_code;
}
catch (const std::bad_alloc &)
{
    return 1;
}
catch (const std::length_error &)
{
    return 1;
}

#if !defined(_DEBUG)

int WINAPI WinMain(
    HINSTANCE hInstance,     /* handle to current instance */
    HINSTANCE hPrevInstance, /* handle to previous instance */
    LPSTR lpCmdLine,         /* pointer to command line */
    int nCmdShow             /* show state of window */
)
{
    return AppMain();
}

#else

int main(int argc, const char *argv[])
{
    return AppMain();
}

#endif
