// Test-only UIA provider: deterministic composition states, not a real IME.
#include <windows.h>
#include <UIAutomation.h>
#include <cstdio>

static volatile LONG mode = 0;
static volatile LONG active_calls = 0;
static HWND edit;
static HWND parent;

class Range : public ITextRangeProvider
{
	LONG refs = 1;
public:
	HRESULT STDMETHODCALLTYPE QueryInterface(REFIID iid, void **out) override
	{
		*out = nullptr;
		if (iid != __uuidof(IUnknown) && iid != __uuidof(ITextRangeProvider)) return E_NOINTERFACE;
		*out = this; AddRef(); return S_OK;
	}
	ULONG STDMETHODCALLTYPE AddRef() override { return InterlockedIncrement(&refs); }
	ULONG STDMETHODCALLTYPE Release() override { return InterlockedDecrement(&refs); }
	HRESULT STDMETHODCALLTYPE Clone(ITextRangeProvider **out) override { *out = this; AddRef(); return S_OK; }
	HRESULT STDMETHODCALLTYPE Compare(ITextRangeProvider *, BOOL *) override { return E_NOTIMPL; }
	HRESULT STDMETHODCALLTYPE CompareEndpoints(TextPatternRangeEndpoint, ITextRangeProvider *, TextPatternRangeEndpoint, int *out) override { *out = mode == 10 ? 0 : -1; return S_OK; }
	HRESULT STDMETHODCALLTYPE ExpandToEnclosingUnit(TextUnit) override { return E_NOTIMPL; }
	HRESULT STDMETHODCALLTYPE FindAttribute(TEXTATTRIBUTEID, VARIANT, BOOL, ITextRangeProvider **) override { return E_NOTIMPL; }
	HRESULT STDMETHODCALLTYPE FindText(BSTR, BOOL, BOOL, ITextRangeProvider **) override { return E_NOTIMPL; }
	HRESULT STDMETHODCALLTYPE GetAttributeValue(TEXTATTRIBUTEID, VARIANT *) override { return E_NOTIMPL; }
	HRESULT STDMETHODCALLTYPE GetBoundingRectangles(SAFEARRAY **) override { return E_NOTIMPL; }
	HRESULT STDMETHODCALLTYPE GetEnclosingElement(IRawElementProviderSimple **) override { return E_NOTIMPL; }
	HRESULT STDMETHODCALLTYPE GetText(int, BSTR *) override { return E_NOTIMPL; }
	HRESULT STDMETHODCALLTYPE Move(TextUnit, int, int *) override { return E_NOTIMPL; }
	HRESULT STDMETHODCALLTYPE MoveEndpointByUnit(TextPatternRangeEndpoint, TextUnit, int, int *) override { return E_NOTIMPL; }
	HRESULT STDMETHODCALLTYPE MoveEndpointByRange(TextPatternRangeEndpoint, ITextRangeProvider *, TextPatternRangeEndpoint) override { return E_NOTIMPL; }
	HRESULT STDMETHODCALLTYPE Select() override { return E_NOTIMPL; }
	HRESULT STDMETHODCALLTYPE AddToSelection() override { return E_NOTIMPL; }
	HRESULT STDMETHODCALLTYPE RemoveFromSelection() override { return E_NOTIMPL; }
	HRESULT STDMETHODCALLTYPE ScrollIntoView(BOOL) override { return E_NOTIMPL; }
	HRESULT STDMETHODCALLTYPE GetChildren(SAFEARRAY **) override { return E_NOTIMPL; }
};

static Range range;

class Provider : public IRawElementProviderSimple, public ITextEditProvider,
	public IRawElementProviderFragment, public IRawElementProviderFragmentRoot
{
	LONG refs = 1;
	bool text;
	bool windowless;
public:
	explicit Provider(bool text, bool windowless = false) : text(text), windowless(windowless) {}
	HRESULT STDMETHODCALLTYPE QueryInterface(REFIID iid, void **out) override
	{
		*out = nullptr;
		if (iid == __uuidof(IUnknown) || iid == __uuidof(IRawElementProviderSimple))
			*out = static_cast<IRawElementProviderSimple *>(this);
		else if (iid == __uuidof(ITextProvider) || iid == __uuidof(ITextEditProvider))
			*out = static_cast<ITextEditProvider *>(this);
		else if (text && iid == __uuidof(IRawElementProviderFragment))
			*out = static_cast<IRawElementProviderFragment *>(this);
		else if (text && !windowless && iid == __uuidof(IRawElementProviderFragmentRoot))
			*out = static_cast<IRawElementProviderFragmentRoot *>(this);
		else return E_NOINTERFACE;
		AddRef(); return S_OK;
	}
	ULONG STDMETHODCALLTYPE AddRef() override { return InterlockedIncrement(&refs); }
	ULONG STDMETHODCALLTYPE Release() override { return InterlockedDecrement(&refs); }
	HRESULT STDMETHODCALLTYPE get_ProviderOptions(ProviderOptions *out) override
	{
		*out = ProviderOptions_ServerSideProvider | ProviderOptions_UseComThreading; return S_OK;
	}
	HRESULT STDMETHODCALLTYPE GetPatternProvider(PATTERNID id, IUnknown **out) override
	{
		*out = nullptr;
		if (text && id == UIA_TextEditPatternId && (windowless ? mode != 8 : mode != 2))
		{
			*out = static_cast<ITextEditProvider *>(this); AddRef();
		}
		return S_OK;
	}
	HRESULT STDMETHODCALLTYPE GetPropertyValue(PROPERTYID id, VARIANT *out) override
	{
		VariantInit(out);
		if (id == UIA_ControlTypePropertyId) { out->vt = VT_I4; out->lVal = UIA_EditControlTypeId; }
		if (id == UIA_IsControlElementPropertyId || id == UIA_IsContentElementPropertyId || id == UIA_HasKeyboardFocusPropertyId)
		{
			out->vt = VT_BOOL;
			out->boolVal = id != UIA_HasKeyboardFocusPropertyId || ((windowless || !text) && mode >= 6) ? VARIANT_TRUE : VARIANT_FALSE;
		}
		return S_OK;
	}
	HRESULT STDMETHODCALLTYPE get_HostRawElementProvider(IRawElementProviderSimple **out) override
	{
		if (windowless) { *out = nullptr; return S_OK; }
		return UiaHostProviderFromHwnd(text ? edit : parent, out);
	}
	HRESULT STDMETHODCALLTYPE Navigate(NavigateDirection direction, IRawElementProviderFragment **out) override;
	HRESULT STDMETHODCALLTYPE GetRuntimeId(SAFEARRAY **out) override
	{
		*out = nullptr;
		if (!windowless) return S_OK;
		*out = SafeArrayCreateVector(VT_I4, 0, 2);
		if (!*out) return E_OUTOFMEMORY;
		LONG index = 0, value = UiaAppendRuntimeId;
		SafeArrayPutElement(*out, &index, &value);
		index = 1; value = 1;
		return SafeArrayPutElement(*out, &index, &value);
	}
	HRESULT STDMETHODCALLTYPE get_BoundingRectangle(UiaRect *out) override { *out = {0, 0, 300, 160}; return S_OK; }
	HRESULT STDMETHODCALLTYPE GetEmbeddedFragmentRoots(SAFEARRAY **out) override { *out = nullptr; return S_OK; }
	HRESULT STDMETHODCALLTYPE SetFocus() override { return E_NOTIMPL; }
	HRESULT STDMETHODCALLTYPE get_FragmentRoot(IRawElementProviderFragmentRoot **out) override;
	HRESULT STDMETHODCALLTYPE ElementProviderFromPoint(double, double, IRawElementProviderFragment **out) override { *out = nullptr; return S_OK; }
	HRESULT STDMETHODCALLTYPE GetFocus(IRawElementProviderFragment **out) override;
	HRESULT STDMETHODCALLTYPE GetSelection(SAFEARRAY **) override { return E_NOTIMPL; }
	HRESULT STDMETHODCALLTYPE GetVisibleRanges(SAFEARRAY **) override { return E_NOTIMPL; }
	HRESULT STDMETHODCALLTYPE RangeFromChild(IRawElementProviderSimple *, ITextRangeProvider **) override { return E_NOTIMPL; }
	HRESULT STDMETHODCALLTYPE RangeFromPoint(UiaPoint, ITextRangeProvider **) override { return E_NOTIMPL; }
	HRESULT STDMETHODCALLTYPE get_DocumentRange(ITextRangeProvider **out) override { return range.Clone(out); }
	HRESULT STDMETHODCALLTYPE get_SupportedTextSelection(SupportedTextSelection *out) override { *out = SupportedTextSelection_None; return S_OK; }
	HRESULT STDMETHODCALLTYPE GetActiveComposition(ITextRangeProvider **out) override
	{
		*out = nullptr;
		LONG current = mode;
		if (windowless)
		{
			if (current == 9) return E_ACCESSDENIED;
			return current == 6 || current == 10 ? range.Clone(out) : S_OK;
		}
		if (current == 3) return E_ACCESSDENIED;
		if (current == 5) return E_NOTIMPL;
		if (current == 4)
		{
			InterlockedIncrement(&active_calls);
			Sleep(2000);
			InterlockedDecrement(&active_calls);
		}
		if (current == 1) return range.Clone(out);
		return S_OK;
	}
	HRESULT STDMETHODCALLTYPE GetConversionTarget(ITextRangeProvider **out) override { *out = nullptr; return S_OK; }
};

static Provider provider(true);
static Provider parent_provider(false);
static Provider virtual_provider(true, true);

HRESULT Provider::Navigate(NavigateDirection direction, IRawElementProviderFragment **out)
{
	*out = nullptr;
	if (windowless && direction == NavigateDirection_Parent) *out = &provider;
	if (text && !windowless && (direction == NavigateDirection_FirstChild || direction == NavigateDirection_LastChild))
		*out = &virtual_provider;
	if (*out) (*out)->AddRef();
	return S_OK;
}

HRESULT Provider::get_FragmentRoot(IRawElementProviderFragmentRoot **out)
{
	*out = &provider; provider.AddRef(); return S_OK;
}

HRESULT Provider::GetFocus(IRawElementProviderFragment **out)
{
	*out = mode >= 6 ? &virtual_provider : nullptr;
	if (*out) (*out)->AddRef();
	return S_OK;
}

static LRESULT CALLBACK procedure(HWND hwnd, UINT msg, WPARAM wp, LPARAM lp)
{
	if (msg == WM_GETOBJECT && static_cast<LONG>(lp) == UiaRootObjectId)
		return UiaReturnRawElementProvider(hwnd, wp, lp, hwnd == edit ? &provider : &parent_provider);
	if (msg == WM_APP) { InterlockedExchange(&mode, static_cast<LONG>(wp)); return 1; }
	if (msg == WM_APP + 1) return active_calls;
	if (msg == WM_APP + 2) { Sleep(2000); return 1; }
	if (msg == WM_CLOSE) { DestroyWindow(hwnd); return 0; }
	if (msg == WM_DESTROY && hwnd != edit) PostQuitMessage(0);
	return DefWindowProcW(hwnd, msg, wp, lp);
}

int main()
{
	if (FAILED(CoInitializeEx(nullptr, COINIT_MULTITHREADED))) return 1;
	WNDCLASSW wc = {};
	wc.lpfnWndProc = procedure; wc.hInstance = GetModuleHandleW(nullptr); wc.lpszClassName = L"ReCraftImeTest";
	if (!RegisterClassW(&wc)) return 2;
	parent = CreateWindowW(wc.lpszClassName, L"IME test", WS_OVERLAPPEDWINDOW,
		0, 0, 320, 200, nullptr, nullptr, wc.hInstance, nullptr);
	edit = CreateWindowW(wc.lpszClassName, L"TextEdit provider", WS_CHILD | WS_VISIBLE,
		0, 0, 300, 160, parent, nullptr, wc.hInstance, nullptr);
	if (!parent || !edit) return 3;
	ShowWindow(parent, SW_SHOWNOACTIVATE);
	std::printf("%llu %llu\n", reinterpret_cast<unsigned long long>(parent), reinterpret_cast<unsigned long long>(edit));
	std::fflush(stdout);
	MSG msg;
	while (GetMessageW(&msg, nullptr, 0, 0) > 0) { TranslateMessage(&msg); DispatchMessageW(&msg); }
	UiaDisconnectProvider(&provider);
	UiaDisconnectProvider(&parent_provider);
	UiaDisconnectProvider(&virtual_provider);
	CoUninitialize();
	return 0;
}
