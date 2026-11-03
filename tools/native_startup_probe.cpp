#include <windows.h>
#include <shellapi.h>
#include <string>
#include <vector>
#include <algorithm>
#include <cstdio>
#include <cstdlib>
#include <new>
#include <crtdbg.h>

static bool fail_allocation = false;
void *operator new(size_t size)
{
    if (fail_allocation && size >= MAX_PATH * sizeof(wchar_t))
    {
        fail_allocation = false;
        throw std::bad_alloc();
    }
    if (void *memory = std::malloc(size))
        return memory;
    throw std::bad_alloc();
}
void operator delete(void *memory) noexcept { std::free(memory); }
void operator delete(void *memory, size_t) noexcept { std::free(memory); }

static std::wstring module_path, saved_path;
static std::vector<std::wstring> path_values;
static std::vector<DWORD> module_capacities, path_capacities;
static size_t path_call;
static DWORD module_error, path_error, oversized_length;
static bool set_failure, real_queries;
static bool path_error_after_query;
static int set_calls;

static DWORD WINAPI probe_module(HMODULE module, LPWSTR buffer, DWORD capacity)
{
    module_capacities.push_back(capacity);
    if (real_queries)
        return GetModuleFileNameW(module, buffer, capacity);
    if (module_error)
    {
        SetLastError(module_error);
        return 0;
    }
    DWORD length = (DWORD)module_path.size();
    // Deliberately omit the terminator to check the returned-length boundary.
    std::copy_n(module_path.data(), (length < capacity) ? length : capacity, buffer);
    return (length < capacity) ? length : capacity;
}

static DWORD WINAPI probe_get(LPCWSTR name, LPWSTR buffer, DWORD capacity)
{
    path_capacities.push_back(capacity);
    if (real_queries)
        return GetEnvironmentVariableW(name, buffer, capacity);
    if (path_error && (!path_error_after_query || path_call > 0))
    {
        SetLastError(path_error);
        return 0;
    }
    if (oversized_length)
        return oversized_length;
    const auto &value = path_values[(path_call < path_values.size()) ? path_call : path_values.size() - 1];
    ++path_call;
    if (capacity <= value.size())
        return (DWORD)value.size() + 1;
    std::copy(value.begin(), value.end(), buffer);
    buffer[value.size()] = L'\0';
    return (DWORD)value.size();
}

static BOOL WINAPI probe_set(LPCWSTR name, LPCWSTR value)
{
    ++set_calls;
    saved_path = value;
    return !set_failure;
}

#define GetModuleFileNameW probe_module
#define GetEnvironmentVariableW probe_get
#define SetEnvironmentVariableW probe_set
#define main launcher_main
#define WinMain launcher_winmain
#include "../clnch/main.cpp"
#undef main
#undef WinMain
#undef GetModuleFileNameW
#undef GetEnvironmentVariableW
#undef SetEnvironmentVariableW

static int failures;
static void check(bool condition, const char *label)
{
    if (!condition)
    {
        std::fprintf(stderr, "FAIL: %s\n", label);
        ++failures;
    }
}

static void reset()
{
    module_path = L"C:\\app\\reclnch.exe";
    path_values = {L"original;日本語😀"};
    path_call = 0;
    module_error = path_error = oversized_length = 0;
    set_failure = real_queries = false;
    path_error_after_query = false;
    set_calls = 0;
    module_capacities.clear();
    path_capacities.clear();
    saved_path.clear();
}

int main()
{
    SetErrorMode(SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX);
#if defined(_DEBUG)
    _CrtSetReportMode(_CRT_ASSERT, _CRTDBG_MODE_FILE);
    _CrtSetReportFile(_CRT_ASSERT, _CRTDBG_FILE_STDERR);
#endif
    std::wstring directory;
    for (size_t length : {12, 259, 260, 261, 519, 520, 1000, 32767})
    {
        reset();
        module_path = L"C:\\" + std::wstring(length - 11, L'x') + L"\\app.exe";
        if (length == 32767)
            path_values = {L""};
        std::wstring expected = module_path.substr(0, module_path.find_last_of(L'\\'));
        check(SetupEnvironment(directory), "module path boundary succeeds");
        check(directory == expected, "module path is complete and split normally");
        check(saved_path == expected + L"/lib;" + path_values.back(), "unchanged PATH prefix and suffix");
        check(path_capacities == std::vector<DWORD>{0, (DWORD)path_values[0].size() + 1}, "capacity uses WCHARs including NUL");
    }
    reset();
    module_path.assign(32768, L'x');
    check(!SetupEnvironment(directory) && set_calls == 0, "module truncation at limit rejected");
    reset();
    module_error = ERROR_ACCESS_DENIED;
    check(AppMain() == 1 && set_calls == 0, "module failure stops before Python");
    for (const auto &values : std::vector<std::vector<std::wstring>>{
             {L"a", std::wstring(1000, L'b'), L"grown"}, {L"long value", L"x"}, {L"a", L""}, {L""}})
    {
        reset();
        path_values = values;
        check(SetupEnvironment(directory), "PATH resize or empty succeeds");
        check(saved_path == L"C:\\app/lib;" + values.back(), "latest full PATH used");
    }
    for (DWORD error : {ERROR_ENVVAR_NOT_FOUND, ERROR_ACCESS_DENIED})
    {
        for (bool after_query : {false, true})
        {
            reset();
            path_error = error;
            path_error_after_query = after_query;
            check(SetupEnvironment(directory) == (error == ERROR_ENVVAR_NOT_FOUND), "missing PATH differs from retrieval failure");
            if (error == ERROR_ENVVAR_NOT_FOUND)
                check(saved_path == L"C:\\app/lib;", "disappeared PATH is empty");
        }
    }
    reset();
    oversized_length = MAXDWORD;
    check(AppMain() == 1 && set_calls == 0, "huge capacity rejected before allocation");
    for (size_t size : {32755, 32756, 32767})
    {
        reset();
        path_values = {std::wstring(size, L'x')};
        check(SetupEnvironment(directory) == (size + std::wstring(L"C:\\app/lib;").size() < 32767), "combined PATH length boundary");
    }
    reset();
    set_failure = true;
    check(AppMain() == 1, "PATH write failure stops before Python");
    reset();
    fail_allocation = true;
    check(AppMain() == 1 && set_calls == 0, "allocation failure stops safely");
    reset();
    real_queries = true;
    check(SetupEnvironment(directory), "real Windows queries succeed");
    wchar_t real_module[32768];
    DWORD length = GetModuleFileNameW(NULL, real_module, 32768);
    std::wstring expected(real_module, length);
    expected.resize(expected.find_last_of(L"\\/"));
    check(directory == expected, "real executable directory unchanged");
    std::printf("Native startup boundary checks: %d failures\n", failures);
    return failures ? 1 : 0;
}
