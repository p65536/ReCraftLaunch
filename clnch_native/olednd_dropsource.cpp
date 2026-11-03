#include "olednd_dropsource.h"

HRESULT __stdcall CDropSource::QueryInterface(const IID &iid, void **ppv)
{
	HRESULT hr;

	if (iid == IID_IDropSource || iid == IID_IUnknown)
	{
		hr = S_OK;
		*ppv = (void *)this;
		AddRef();
	}
	else
	{
		hr = E_NOINTERFACE;
		*ppv = 0;
	}
	return hr;
}

ULONG __stdcall CDropSource::AddRef()
{
	InterlockedIncrement(&_RefCount);
	return (ULONG)_RefCount;
}

ULONG __stdcall CDropSource::Release()
{
	ULONG ret = (ULONG)InterlockedDecrement(&_RefCount);
	if (ret == 0)
	{
		delete this;
	}
	return ret;
}

HRESULT __stdcall CDropSource::QueryContinueDrag(BOOL fEscapePressed, DWORD grfKeyState)
{
	/* Determine whether dragging should continue. */

	/* Cancel if Escape or both mouse buttons are pressed. */
	if (fEscapePressed || (MK_LBUTTON | MK_RBUTTON) == (grfKeyState & (MK_LBUTTON | MK_RBUTTON)))
	{
		return DRAGDROP_S_CANCEL;
	}

	/* Drop when both mouse buttons are released. */
	if ((grfKeyState & (MK_LBUTTON | MK_RBUTTON)) == 0)
	{
		return DRAGDROP_S_DROP;
	}
	return S_OK;
}

HRESULT __stdcall CDropSource::GiveFeedback(DWORD dwEffect)
{
	/* Custom cursor feedback would be handled here. */

	// Use the default mouse cursors.
	return DRAGDROP_S_USEDEFAULTCURSORS;
}
