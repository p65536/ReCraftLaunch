#include <vector>
#include <algorithm>
#include <climits>
#include <cwchar>
#include <new>

#include <windows.h>
#include <shellscalingapi.h>

#if defined(_DEBUG)
#undef _DEBUG
#include "python.h"
#define _DEBUG
#else
#include "python.h"
#endif

#include "structmember.h"
#include "frameobject.h"

#include "pythonutil.h"
#include "ckitcore.h"

using namespace ckit;

//-----------------------------------------------------------------------------

#define MODULE_NAME "ckitcore"

static std::wstring WINDOW_CLASS_NAME = L"CkitWindowClass";
static std::wstring TASKTRAY_WINDOW_CLASS_NAME = L"CkitTaskTrayWindowClass";
static UINT WM_TASKBAR_CREATED = RegisterWindowMessage(L"TaskbarCreated");

static PyObject *Error;
static PyObject *command_info_constructor;

const int ORIGIN_X_LEFT = 0;
const int ORIGIN_X_CENTER = 1 << 0;
const int ORIGIN_X_RIGHT = 1 << 1;
const int ORIGIN_Y_TOP = 0;
const int ORIGIN_Y_CENTER = 1 << 2;
const int ORIGIN_Y_BOTTOM = 1 << 3;

const int MOUSE_CURSOR_APPSTARTING = 1;
const int MOUSE_CURSOR_ARROW = 2;
const int MOUSE_CURSOR_CROSS = 3;
const int MOUSE_CURSOR_HAND = 4;
const int MOUSE_CURSOR_HELP = 5;
const int MOUSE_CURSOR_IBEAM = 6;
const int MOUSE_CURSOR_NO = 7;
const int MOUSE_CURSOR_SIZEALL = 8;
const int MOUSE_CURSOR_SIZENESW = 9;
const int MOUSE_CURSOR_SIZENS = 10;
const int MOUSE_CURSOR_SIZENWSE = 11;
const int MOUSE_CURSOR_SIZEWE = 12;
const int MOUSE_CURSOR_UPARROW = 13;
const int MOUSE_CURSOR_WAIT = 14;

const int WM_USER_NTFYICON = WM_USER + 100;
const int ID_MENUITEM = 256;
const int ID_MENUITEM_MAX = 256 + 1024 - 1;
const int ID_POPUP_MENUITEM = ID_MENUITEM_MAX + 1;
const int ID_POPUP_MENUITEM_MAX = ID_POPUP_MENUITEM + 1024;

const int TIMER_PAINT = 0x101;
const int TIMER_PAINT_INTERVAL = 10;
const int TIMER_CARET_BLINK = 0x102;
const int TIMER_TASKTRAY_RETRY = 0x103;

//-----------------------------------------------------------------------------

//-----------------------------------------------------------------------------

Image::Image(int _width, int _height, const char *pixels, const COLORREF *_transparent_color, bool _halftone)
	: width(_width),
	  height(_height),
	  transparent(_transparent_color != 0),
	  halftone(_halftone),
	  transparent_color(_transparent_color ? *_transparent_color : 0),
	  ref_count(0)
{
	handle = NULL;
	HDC hDC = GetDC(NULL);
	if (!hDC)
	{
		PyErr_SetString(PyExc_RuntimeError, "GetDC failed while creating image.");
		return;
	}
	handle = CreateCompatibleBitmap(hDC, width, height);
	if (!handle)
	{
		ReleaseDC(NULL, hDC);
		PyErr_SetString(PyExc_RuntimeError, "CreateCompatibleBitmap failed.");
		return;
	}

	BITMAPINFO info = {0};
	info.bmiHeader.biSize = sizeof(BITMAPINFOHEADER);
	info.bmiHeader.biWidth = width;
	info.bmiHeader.biHeight = height;
	info.bmiHeader.biPlanes = 1;
	info.bmiHeader.biBitCount = 32;

	if (pixels)
	{
		if (SetDIBits(NULL, handle, 0, height, pixels, &info, DIB_RGB_COLORS) != height)
		{
			DeleteObject(handle);
			handle = NULL;
			PyErr_SetString(PyExc_RuntimeError, "SetDIBits failed.");
		}
	}

	ReleaseDC(NULL, hDC);
}

Image::~Image()
{
	DeleteObject(handle);
}

//-----------------------------------------------------------------------------

Font::Font(const wchar_t *name, int height, int padding)
	: handle(0),
	  char_width(0),
	  char_height(0),
	  vertical_padding(padding > 0 ? padding : 0),
	  ref_count(0)
{
	size_t name_length = wcslen(name);
	if (name_length >= _countof(logfont.lfFaceName))
	{
		PyErr_SetString(PyExc_ValueError, "font name must be shorter than LF_FACESIZE (32 UTF-16 code units).");
		return;
	}
	if (height == INT_MIN)
	{
		PyErr_SetString(PyExc_OverflowError, "font size cannot be negated as a C int.");
		return;
	}

	// Allocate before acquiring GDI resources so bad_alloc cannot leak handles.
	std::vector<int> char_width_table(0x10000);
	zenkaku_table.resize(0x10000);
	HDC hDC = NULL;
	HGDIOBJ oldfont = NULL;
	TEXTMETRIC met;
	long long width = 0;
	long long cell_height = 0;

	memset(&logfont, 0, sizeof(logfont));
	logfont.lfHeight = -height;
	logfont.lfWidth = 0;
	logfont.lfEscapement = 0;
	logfont.lfOrientation = 0;
	logfont.lfWeight = FW_NORMAL;
	logfont.lfItalic = 0;
	logfont.lfUnderline = 0;
	logfont.lfStrikeOut = 0;
	logfont.lfCharSet = DEFAULT_CHARSET;
	logfont.lfOutPrecision = OUT_DEFAULT_PRECIS;
	logfont.lfClipPrecision = CLIP_DEFAULT_PRECIS;

	logfont.lfQuality = DEFAULT_QUALITY; // May behave like CLEARTYPE_QUALITY depending on the OS settings.
										 // logfont.lfQuality = CLEARTYPE_QUALITY; // Previously observed to be faster than ANTIALIASED_QUALITY.
										 // logfont.lfQuality = ANTIALIASED_QUALITY; // Previously observed to be slow with ClearType enabled.

	logfont.lfPitchAndFamily = FIXED_PITCH | FF_DONTCARE;
	memcpy(logfont.lfFaceName, name, (name_length + 1) * sizeof(*name));

	handle = CreateFontIndirect(&logfont);
	if (!handle)
	{
		PyErr_SetString(PyExc_RuntimeError, "CreateFontIndirect failed.");
		return;
	}

	hDC = GetDC(NULL);
	if (!hDC)
	{
		PyErr_SetString(PyExc_RuntimeError, "GetDC failed while creating font.");
		goto failed;
	}
	oldfont = SelectObject(hDC, handle);
	if (!oldfont || oldfont == HGDI_ERROR)
	{
		oldfont = NULL;
		PyErr_SetString(PyExc_RuntimeError, "SelectObject failed while creating font.");
		goto failed;
	}

	if (!GetTextMetrics(hDC, &met) || !GetCharWidth32(hDC, 0, 0xffff, char_width_table.data()))
	{
		PyErr_SetString(PyExc_RuntimeError, "font measurement failed.");
		goto failed;
	}

	// Build the table that distinguishes single-cell and double-cell characters.
	for (int i = 0; i < 26; i++)
	{
		width += char_width_table['A' + i];
		width += char_width_table['a' + i];
	}
	width /= 26 * 2;
	cell_height = (long long)met.tmHeight + (long long)vertical_padding * 2;
	if (cell_height > INT_MAX)
	{
		PyErr_SetString(PyExc_OverflowError, "font cell height exceeds C int range.");
		goto failed;
	}
	if (width <= 0 || cell_height <= 0)
	{
		PyErr_SetString(PyExc_RuntimeError, "font measurement returned invalid cell dimensions.");
		goto failed;
	}
	char_width = (int)width;
	// Cell height includes padding; the GDI font size stays unchanged.
	char_height = (int)cell_height;
	for (int i = 0; i <= 0xffff; i++)
	{
		zenkaku_table[i] = char_width_table[i] > char_width;
	}

	SelectObject(hDC, oldfont);
	ReleaseDC(NULL, hDC);
	return;

failed:
	if (oldfont)
		SelectObject(hDC, oldfont);
	if (hDC)
		ReleaseDC(NULL, hDC);
	DeleteObject(handle);
	handle = NULL;
}

Font::~Font()
{
	if (handle)
		DeleteObject(handle);
}

//-----------------------------------------------------------------------------

Plane::Plane(Window *_window, int _x, int _y, int _width, int _height, float _priority)
	: window(_window),
	  show(true),
	  x(_x),
	  y(_y),
	  width(_width),
	  height(_height),
	  priority(_priority)
{
}

Plane::~Plane()
{
	RECT dirty_rect = {x, y, x + width, y + height};
	window->appendDirtyRect(dirty_rect);
}

void Plane::Show(bool _show)
{
	if (show == _show)
		return;

	show = _show;

	RECT dirty_rect = {x, y, x + width, y + height};
	window->appendDirtyRect(dirty_rect);
}

void Plane::SetPosition(int _x, int _y)
{
	if (x == _x && y == _y)
		return;

	RECT dirty_rect = {x, y, x + width, y + height};
	window->appendDirtyRect(dirty_rect);

	x = _x;
	y = _y;

	RECT dirty_rect2 = {x, y, x + width, y + height};
	window->appendDirtyRect(dirty_rect2);
}

void Plane::SetSize(int _width, int _height)
{
	if (width == _width && height == _height)
		return;

	RECT dirty_rect = {x, y, x + width, y + height};
	window->appendDirtyRect(dirty_rect);

	width = _width;
	height = _height;

	RECT dirty_rect2 = {x, y, x + width, y + height};
	window->appendDirtyRect(dirty_rect2);
}

void Plane::SetPriority(float _priority)
{
	if (priority == _priority)
		return;

	priority = _priority;
	// list::sort is stable, preserving the existing order of equal priorities.
	window->plane_list.sort([](const Plane *a, const Plane *b) { return a->priority > b->priority; });

	RECT dirty_rect = {x, y, x + width, y + height};
	window->appendDirtyRect(dirty_rect);
}

//-----------------------------------------------------------------------------

ImagePlane::ImagePlane(Window *_window, int _x, int _y, int _width, int _height, float _priority)
	: Plane(_window, _x, _y, _width, _height, _priority),
	  pyobj(NULL),
	  image(NULL)
{
}

ImagePlane::~ImagePlane()
{
	if (image)
		image->Release();

	((ImagePlane_Object *)pyobj)->p = NULL;
	Py_XDECREF(pyobj);
	pyobj = NULL;
}

void ImagePlane::SetPyObject(PyObject *_pyobj)
{
	if (pyobj != _pyobj)
	{
		Py_XDECREF(pyobj);
		pyobj = _pyobj;
		Py_XINCREF(pyobj);
	}
}

void ImagePlane::SetImage(Image *_image)
{
	if (image == _image)
		return;

	if (image)
		image->Release();

	image = _image;

	if (image)
		image->AddRef();

	RECT dirty_rect = {x, y, x + width, y + height};
	window->appendDirtyRect(dirty_rect);
}

void ImagePlane::Draw(const RECT &paint_rect)
{
	if (!show)
	{
		return;
	}

	RECT plane_rect = {x, y, x + width, y + height};
	if (plane_rect.left >= paint_rect.right || plane_rect.right <= paint_rect.left || plane_rect.top >= paint_rect.bottom || plane_rect.bottom <= paint_rect.top)
	{
		return;
	}

	if (image)
	{
		HDC compatibleDC = CreateCompatibleDC(window->offscreen_dc);

		SelectObject(compatibleDC, image->handle);

		if (image->halftone)
		{
			SetStretchBltMode(window->offscreen_dc, STRETCH_HALFTONE);
		}
		else
		{
			SetStretchBltMode(window->offscreen_dc, STRETCH_DELETESCANS);
		}

		if (image->transparent)
		{
			TransparentBlt(
				window->offscreen_dc, x, y, width, height,
				compatibleDC, 0, 0, image->width, image->height,
				image->transparent_color);

		}
		else
		{
			StretchBlt(
				window->offscreen_dc, x, y, width, height,
				compatibleDC, 0, 0, image->width, image->height,
				SRCCOPY);

		}

		DeleteDC(compatibleDC);
	}
}

//-----------------------------------------------------------------------------

TextPlane::TextPlane(Window *_window, int _x, int _y, int _width, int _height, float _priority)
	: Plane(_window, _x, _y, _width, _height, _priority),
	  pyobj(NULL),
	  font(NULL),
	  offscreen_dc(0),
	  offscreen_bmp(0),
	  offscreen_buf(0),
	  dirty(true)
{
	offscreen_size.cx = 0;
	offscreen_size.cy = 0;
}

TextPlane::~TextPlane()
{
	if (offscreen_dc)
	{
		DeleteDC(offscreen_dc);
	}
	if (font)
	{
		font->Release();
	}
	if (offscreen_bmp)
	{
		DeleteObject(offscreen_bmp);
	}

	{
		std::vector<Line *>::iterator i;
		for (i = char_buffer.begin(); i != char_buffer.end(); i++)
		{
			delete (*i);
		}
		char_buffer.clear();
	}

	((TextPlane_Object *)pyobj)->p = NULL;
	Py_XDECREF(pyobj);
	pyobj = NULL;
}

void TextPlane::SetPyObject(PyObject *_pyobj)
{
	if (pyobj != _pyobj)
	{
		Py_XDECREF(pyobj);
		pyobj = _pyobj;
		Py_XINCREF(pyobj);
	}
}

void TextPlane::SetFont(Font *_font)
{
	if (font == _font)
		return;

	if (font)
		font->Release();

	font = _font;

	if (font)
		font->AddRef();

	// Invalidate the whole plane after changing its font.
	dirty = true;

	RECT dirty_rect = {x, y, x + width, y + height};
	window->appendDirtyRect(dirty_rect);
}

static inline void PutChar(Line *line, int pos, const Char &chr, bool *modified)
{
	if (pos < 0 || (size_t)pos > line->size())
		return;
	if (line->size() == (size_t)pos)
	{
		line->push_back(chr);
		*modified = true;
	}
	else if ((*line)[pos] != chr)
	{
		(*line)[pos] = chr;
		*modified = true;
	}
}

void TextPlane::PutString(int x, int y, int width, int height, const Attribute &attr, const wchar_t *str, int offset)
{
	if (x < 0 || y < 0 || width <= 0 || height <= 0 || !*str)
		return;

	// Only visible cells need storage; widen before adding untrusted coordinates.
	int columns = this->width / font->char_width;
	int rows = this->height / font->char_height;
	long long right = (std::min)((long long)x + width, (long long)columns);
	if (x >= right || y >= rows)
		return;
	long long pos = (long long)x + offset;
	if (pos >= right)
		return;

	long long left_px = (long long)x * font->char_width + this->x;
	long long top_px = (long long)y * font->char_height + this->y;
	long long right_px = right * font->char_width + this->x;
	long long bottom_px = (std::min)((long long)y + height, (long long)rows) * font->char_height + this->y;
	if (left_px < INT_MIN || top_px < INT_MIN || right_px > INT_MAX || bottom_px > INT_MAX)
	{
		PyErr_SetString(PyExc_OverflowError, "putString pixel coordinates exceed C int range.");
		return;
	}

	bool modified = false;
	Line *line = NULL;
	for (; *str && pos < right; ++str)
	{
		int cells = font->zenkaku_table[*str] ? 2 : 1;
		long long next = pos + cells;
		if (next > x)
		{
			// Defer allocation until a character actually intersects the drawing area.
			if (!line)
			{
				char_buffer.reserve((size_t)y + 1);
				while (char_buffer.size() <= (size_t)y)
					char_buffer.push_back(new Line());
				line = char_buffer[y];
				size_t start = (size_t)(std::max)(pos, (long long)x);
				if (line->size() < start)
					line->resize(start, Char(L' '));
			}
			if (pos < x)
				PutChar(line, x, Char(L' ', attr), &modified);
			else if (next > right)
				PutChar(line, (int)pos, Char(L' ', attr), &modified);
			else
			{
				PutChar(line, (int)pos, Char(*str, attr), &modified);
				if (cells == 2)
					PutChar(line, (int)pos + 1, Char(0), &modified);
			}
		}
		pos = next;
	}

	if (modified)
	{
		dirty = true;
		RECT dirty_rect = {(int)left_px, (int)top_px, (int)right_px, (int)bottom_px};
		window->appendDirtyRect(dirty_rect);
	}
}

int TextPlane::GetStringWidth(const wchar_t *str, int tab_width, int offset, int columns[])
{
	long long width = 0;

	int i;
	for (i = 0; str[i]; i++)
	{
		if (columns)
		{
			columns[i] = (int)width;
		}

		if (str[i] == '\t')
		{
			int column = (int)(((long long)offset + width) % tab_width);
			if (column < 0)
				column += tab_width;
			width += tab_width - column;
			if (width > INT_MAX)
				return -1;
			continue;
		}

		width++;

		if (font->zenkaku_table[str[i]])
		{
			width++;
		}
		if (width > INT_MAX)
			return -1;
	}

	if (columns)
	{
		columns[i] = (int)width;
	}

	return (int)width;
}

void TextPlane::Scroll(int x, int y, int width, int height, int delta_x, int delta_y)
{
	BOOL ret;

	// Draw any pending text into the offscreen buffer.
	DrawOffscreen();

	// Cover both source and destination, including upward/leftward moves.
	int rows = y + height + (std::max)(0, delta_y);
	char_buffer.reserve(rows);
	while ((int)char_buffer.size() < rows)
	{
		Line *line = new Line();
		char_buffer.push_back(line);
	}

	// Copy the character buffer.
	if (delta_y < 0)
	{
		for (int i = 0; i < height; ++i)
		{
			*char_buffer[y + i + delta_y] = *char_buffer[y + i];
		}
	}
	else if (delta_y > 0)
	{
		for (int i = height - 1; i >= 0; --i)
		{
			*char_buffer[y + i + delta_y] = *char_buffer[y + i];
		}
	}
	else
	{
		// Pad missing character cells with spaces.
		for (int i = 0; i < height; ++i)
		{
			Line *line = char_buffer[y + i];
			while ((int)line->size() < x + width + (std::max)(0, delta_x))
			{
				line->push_back(Char(L' '));
			}
		}

		if (delta_x < 0)
		{
			for (int i = 0; i < height; ++i)
			{
				for (int j = 0; j < width; ++j)
				{
					(*char_buffer[y + i + delta_y])[x + j + delta_x] = (*char_buffer[y + i])[x + j];
				}
			}
		}
		else
		{
			for (int i = 0; i < height; ++i)
			{
				for (int j = width - 1; j >= 0; --j)
				{
					(*char_buffer[y + i + delta_y])[x + j + delta_x] = (*char_buffer[y + i])[x + j];
				}
			}
		}
	}

	RECT src_rect = {
		x * font->char_width,
		y * font->char_height,
		(x + width) * font->char_width,
		(y + height) * font->char_height};

	ret = ScrollDC(
		offscreen_dc,
		delta_x * font->char_width,
		delta_y * font->char_height,
		&src_rect,
		NULL, NULL, NULL);
	assert(ret);

	RECT dirty_rect = {
		(x + delta_x) * font->char_width + this->x,
		(y + delta_y) * font->char_height + this->y,
		(x + width + delta_x) * font->char_width + this->x,
		(y + height + delta_y) * font->char_height + this->y};

	window->appendDirtyRect(dirty_rect);
}

void TextPlane::DrawOffscreen()
{
	if (!dirty)
	{
		return;
	}

	bool offscreen_rebuilt = false;

	// Create or resize the offscreen buffer.
	if (offscreen_dc == NULL || offscreen_bmp == NULL || offscreen_size.cx != width || offscreen_size.cy != height)
	{
		if (offscreen_dc)
		{
			DeleteDC(offscreen_dc);
		}
		if (offscreen_bmp)
		{
			DeleteObject(offscreen_bmp);
		}

		offscreen_size.cx = width;
		offscreen_size.cy = height;

		if (offscreen_size.cx < 1)
		{
			offscreen_size.cx = 1;
		}
		if (offscreen_size.cy < 1)
		{
			offscreen_size.cy = 1;
		}

		offscreen_dc = CreateCompatibleDC(window->offscreen_dc);
		BITMAPINFO bmi;
		ZeroMemory(&bmi, sizeof(BITMAPINFO));
		bmi.bmiHeader.biSize = sizeof(BITMAPINFOHEADER);
		bmi.bmiHeader.biWidth = offscreen_size.cx;
		bmi.bmiHeader.biHeight = offscreen_size.cy;
		bmi.bmiHeader.biPlanes = 1;
		bmi.bmiHeader.biBitCount = 32;
		bmi.bmiHeader.biCompression = BI_RGB;
		bmi.bmiHeader.biSizeImage = offscreen_size.cx * offscreen_size.cy * 4;
		offscreen_bmp = CreateDIBSection(offscreen_dc, &bmi, DIB_RGB_COLORS, (void **)&offscreen_buf, NULL, 0);
		SelectObject(offscreen_dc, offscreen_bmp);

		offscreen_rebuilt = true;
	}

	int text_width = width / font->char_width;
	int text_height = height / font->char_height;

	wchar_t *work_text = new wchar_t[text_width];
	int *work_width = new int[text_width];
	unsigned int work_len;
	bool work_dirty;

	HGDIOBJ old_font = SelectObject(offscreen_dc, font->handle);

	for (int y = 0; y < (int)char_buffer.size() && y < text_height; ++y)
	{
		Line &line = *(char_buffer[y]);

		for (int x = 0; x < (int)line.size() && x < text_width; ++x)
		{
			Char &chr = line[x];

			work_len = 0;
			work_dirty = false;

			int x2;
			for (x2 = x; x2 < (int)line.size() && x2 < text_width; ++x2)
			{
				Char &chr2 = line[x2];

				if (chr2.c == 0)
				{
					continue;
				}

				if (chr2.c != ' ')
				{
					if (!chr.attr.Equal(chr2.attr))
					{
						break;
					}
				}
				else
				{
					if (!chr.attr.EqualWithoutFgColor(chr2.attr))
					{
						break;
					}
				}

				work_text[work_len] = chr2.c;
				work_width[work_len] = (!font->zenkaku_table[chr2.c]) ? font->char_width : font->char_width * 2;
				work_len++;

				if (chr2.dirty)
				{
					work_dirty = true;
					chr2.dirty = false;
				}
			}

			if (work_dirty || offscreen_rebuilt)
			{
				if (chr.attr.bg & Attribute::BG_Flat)
				{
					HBRUSH hBrush = CreateSolidBrush(chr.attr.bg_color[0]);
					HPEN hPen = CreatePen(PS_SOLID, 0, chr.attr.bg_color[0]);

					HGDIOBJ old_brush = SelectObject(offscreen_dc, hBrush);
					HGDIOBJ old_pen = SelectObject(offscreen_dc, hPen);

					Rectangle(
						offscreen_dc,
						x * font->char_width,
						y * font->char_height,
						x2 * font->char_width,
						(y + 1) * font->char_height);

					if (old_pen)
						SelectObject(offscreen_dc, old_pen);
					if (old_brush)
						SelectObject(offscreen_dc, old_brush);

					DeleteObject(hBrush);
					DeleteObject(hPen);

				}
				else if (chr.attr.bg & Attribute::BG_Gradation)
				{
					TRIVERTEX v[4];

					v[0].x = x * font->char_width;
					v[0].y = y * font->char_height;
					v[0].Red = GetRValue(chr.attr.bg_color[0]) << 8;
					v[0].Green = GetGValue(chr.attr.bg_color[0]) << 8;
					v[0].Blue = GetBValue(chr.attr.bg_color[0]) << 8;
					v[0].Alpha = 255 << 8;

					v[1].x = x2 * font->char_width;
					v[1].y = y * font->char_height;
					v[1].Red = GetRValue(chr.attr.bg_color[1]) << 8;
					v[1].Green = GetGValue(chr.attr.bg_color[1]) << 8;
					v[1].Blue = GetBValue(chr.attr.bg_color[1]) << 8;
					v[1].Alpha = 255 << 8;

					v[2].x = x * font->char_width;
					v[2].y = (y + 1) * font->char_height;
					v[2].Red = GetRValue(chr.attr.bg_color[2]) << 8;
					v[2].Green = GetGValue(chr.attr.bg_color[2]) << 8;
					v[2].Blue = GetBValue(chr.attr.bg_color[2]) << 8;
					v[2].Alpha = 255 << 8;

					v[3].x = x2 * font->char_width;
					v[3].y = (y + 1) * font->char_height;
					v[3].Red = GetRValue(chr.attr.bg_color[3]) << 8;
					v[3].Green = GetGValue(chr.attr.bg_color[3]) << 8;
					v[3].Blue = GetBValue(chr.attr.bg_color[3]) << 8;
					v[3].Alpha = 255 << 8;

					GRADIENT_TRIANGLE triangle[2];
					triangle[0].Vertex1 = 0;
					triangle[0].Vertex2 = 1;
					triangle[0].Vertex3 = 2;
					triangle[1].Vertex1 = 1;
					triangle[1].Vertex2 = 2;
					triangle[1].Vertex3 = 3;

					GradientFill(
						offscreen_dc,
						v,
						4,
						triangle,
						2,
						GRADIENT_FILL_TRIANGLE);

				}
				else
				{
					HBRUSH brush = (HBRUSH)GetStockObject(BLACK_BRUSH);

					RECT rect = {
						x * font->char_width,
						y * font->char_height,
						x2 * font->char_width,
						(y + 1) * font->char_height};

					FillRect(offscreen_dc, &rect, brush);

				}

				if (chr.attr.bg)
				{
					SetTextColor(offscreen_dc, chr.attr.fg_color);
				}
				else
				{
					SetTextColor(offscreen_dc, RGB(0xff, 0xff, 0xff));
				}

				SetBkMode(offscreen_dc, TRANSPARENT);

				ExtTextOut(
					offscreen_dc,
					x * font->char_width,
					y * font->char_height + font->vertical_padding,
					0, NULL,
					(LPCWSTR)work_text,
					(UINT)(work_len),
					work_width);

				if (chr.attr.bg)
				{
					RECT rect = {
						x * font->char_width,
						y * font->char_height,
						x2 * font->char_width,
						(y + 1) * font->char_height};

					// Fill alpha with 255.
					for (int py = rect.top; py < rect.bottom; ++py)
					{
						for (int px = rect.left; px < rect.right; ++px)
						{
							offscreen_buf[(offscreen_size.cy - py - 1) * offscreen_size.cx * 4 + px * 4 + 3] = 0xff;
						}
					}
				}
				else
				{
					RECT rect = {
						x * font->char_width,
						y * font->char_height,
						x2 * font->char_width,
						(y + 1) * font->char_height};

					// Premultiply the color channels by alpha.
					for (int py = rect.top; py < rect.bottom; ++py)
					{
						for (int px = rect.left; px < rect.right; ++px)
						{
							int alpha = offscreen_buf[(offscreen_size.cy - py - 1) * offscreen_size.cx * 4 + px * 4 + 1];
							offscreen_buf[(offscreen_size.cy - py - 1) * offscreen_size.cx * 4 + px * 4 + 0] = GetBValue(chr.attr.fg_color) * alpha / 255;
							offscreen_buf[(offscreen_size.cy - py - 1) * offscreen_size.cx * 4 + px * 4 + 1] = GetGValue(chr.attr.fg_color) * alpha / 255;
							offscreen_buf[(offscreen_size.cy - py - 1) * offscreen_size.cx * 4 + px * 4 + 2] = GetRValue(chr.attr.fg_color) * alpha / 255;
							offscreen_buf[(offscreen_size.cy - py - 1) * offscreen_size.cx * 4 + px * 4 + 3] = alpha;
						}
					}
				}

				for (int line = 0; line < 2; ++line)
				{
					if (chr.attr.line[line] & (Attribute::Line_Left | Attribute::Line_Right | Attribute::Line_Top | Attribute::Line_Bottom))
					{
						if (chr.attr.line[line] & Attribute::Line_Left)
						{
							DrawVerticalLine(
								x * font->char_width,
								y * font->char_height,
								(y + 1) * font->char_height,
								chr.attr.line_color[line],
								(chr.attr.line[line] & Attribute::Line_Dot) != 0);
						}

						if (chr.attr.line[line] & Attribute::Line_Bottom)
						{
							DrawHorizontalLine(
								x * font->char_width,
								(y + 1) * font->char_height - 1,
								x2 * font->char_width,
								chr.attr.line_color[line],
								(chr.attr.line[line] & Attribute::Line_Dot) != 0);
						}

						if (chr.attr.line[line] & Attribute::Line_Right)
						{
							DrawVerticalLine(
								x2 * font->char_width - 1,
								y * font->char_height,
								(y + 1) * font->char_height,
								chr.attr.line_color[line],
								(chr.attr.line[line] & Attribute::Line_Dot) != 0);
						}

						if (chr.attr.line[line] & Attribute::Line_Top)
						{
							DrawHorizontalLine(
								x * font->char_width,
								y * font->char_height,
								x2 * font->char_width,
								chr.attr.line_color[line],
								(chr.attr.line[line] & Attribute::Line_Dot) != 0);
						}
					}
				}
			}

			x = x2 - 1;
		}
	}

	if (old_font)
		SelectObject(offscreen_dc, old_font);

	delete[] work_width;
	delete[] work_text;

	dirty = false;
}

void TextPlane::DrawHorizontalLine(int x1, int y1, int x2, COLORREF color, bool dotted)
{
	color = (0xff << 24) | (GetRValue(color) << 16) | (GetGValue(color) << 8) | GetBValue(color);
	int step;
	if (dotted)
	{
		step = 2;
	}
	else
	{
		step = 1;
	}

	for (int x = x1; x < x2; x += step)
	{
		*(int *)(&offscreen_buf[(offscreen_size.cy - y1 - 1) * offscreen_size.cx * 4 + x * 4 + 0]) = color;
	}
}

void TextPlane::DrawVerticalLine(int x1, int y1, int y2, COLORREF color, bool dotted)
{
	color = (0xff << 24) | (GetRValue(color) << 16) | (GetGValue(color) << 8) | GetBValue(color);
	int step;
	if (dotted)
	{
		step = 2;
	}
	else
	{
		step = 1;
	}

	for (int y = y1; y < y2; y += step)
	{
		*(int *)(&offscreen_buf[(offscreen_size.cy - y - 1) * offscreen_size.cx * 4 + x1 * 4 + 0]) = color;
	}
}

void TextPlane::Draw(const RECT &paint_rect)
{
	// An unconfigured plane stays invisible until SetFont invalidates it.
	if (!show || !font)
	{
		return;
	}

	RECT plane_rect = {x, y, x + width, y + height};
	if (plane_rect.left >= paint_rect.right || plane_rect.right <= paint_rect.left || plane_rect.top >= paint_rect.bottom || plane_rect.bottom <= paint_rect.top)
	{
		return;
	}

	// Draw the text into the offscreen buffer.
	DrawOffscreen();

	// AlphaBlend from the text offscreen buffer.
	{
		RECT _paint_rect = paint_rect;
		if (_paint_rect.left < plane_rect.left)
		{
			_paint_rect.left = plane_rect.left;
		}
		if (_paint_rect.right > plane_rect.right)
		{
			_paint_rect.right = plane_rect.right;
		}
		if (_paint_rect.top < plane_rect.top)
		{
			_paint_rect.top = plane_rect.top;
		}
		if (_paint_rect.bottom > plane_rect.bottom)
		{
			_paint_rect.bottom = plane_rect.bottom;
		}

		int paint_width = _paint_rect.right - _paint_rect.left;
		int paint_height = _paint_rect.bottom - _paint_rect.top;

		BLENDFUNCTION bf;
		bf.BlendOp = AC_SRC_OVER;
		bf.BlendFlags = 0;
		bf.AlphaFormat = AC_SRC_ALPHA;
		bf.SourceConstantAlpha = 255;

		AlphaBlend(
			window->offscreen_dc, _paint_rect.left, _paint_rect.top, paint_width, paint_height,
			offscreen_dc, _paint_rect.left - x, _paint_rect.top - y, paint_width, paint_height,
			bf);
	}
}

void TextPlane::SetCaretPosition(int caret_x, int caret_y)
{
	RECT caret_rect = {};
	if (caret_x != -1 || caret_y != -1)
	{
		caret_rect = {
			caret_x * font->char_width + x,
			caret_y * font->char_height + y + font->vertical_padding,
			caret_x * font->char_width + x + 2,
			(caret_y + 1) * font->char_height + y - font->vertical_padding};
	}

	window->setCaretRect(caret_rect);
	window->setImeFont(font->logfont);
}

//-----------------------------------------------------------------------------

MenuNode::Param::Param()
	: command(NULL),
	  visible(NULL),
	  enabled(NULL),
	  checked(NULL),
	  items(NULL),
	  separator(false)
{
}

MenuNode::MenuNode(Param &param)
	: ref_count(0),
	  separator(false)
{
	name = param.name;
	text = param.text;

	command = param.command;
	Py_XINCREF(command);

	visible = param.visible;
	Py_XINCREF(visible);

	enabled = param.enabled;
	Py_XINCREF(enabled);

	checked = param.checked;
	Py_XINCREF(checked);

	items = param.items;
	Py_XINCREF(items);

	separator = param.separator;
}

MenuNode::~MenuNode()
{
	Py_XDECREF(command);
	command = NULL;
	Py_XDECREF(visible);
	visible = NULL;
	Py_XDECREF(enabled);
	enabled = NULL;
	Py_XDECREF(checked);
	checked = NULL;
	Py_XDECREF(items);
	items = NULL;
}

//-----------------------------------------------------------------------------

Window::Param::Param()
{
	is_winpos_given = false;
	winpos_x = 0;
	winpos_y = 0;
	winsize_w = 100;
	winsize_h = 100;
	origin = 0;
	parent_window = NULL;
	parent_window_hwnd = NULL;
	bg_color = RGB(0x01, 0x01, 0x01);
	frame_color = RGB(0xff, 0xff, 0xff);
	caret0_color = RGB(0xff, 0xff, 0xff);
	caret1_color = RGB(0xff, 0x00, 0x00);
	title_bar = true;
	show = true;
	resizable = true;
	noframe = false;
	minimizebox = true;
	maximizebox = true;
	caret = false;
	is_transparency_given = false;
	transparency = 255;
	is_transparent_color_given = false;
	transparent_color = 0;
	is_top_most = false;
	sysmenu = false;
	tool = false;
	ncpaint = false;

	activate_handler = NULL;
	close_handler = NULL;
	endsession_handler = NULL;
	move_handler = NULL;
	sizing_handler = NULL;
	size_handler = NULL;
	dpi_handler = NULL;
	dropfiles_handler = NULL;
	ipc_handler = NULL;
	keydown_handler = NULL;
	keyup_handler = NULL;
	char_handler = NULL;
	lbuttondown_handler = NULL;
	lbuttonup_handler = NULL;
	mbuttondown_handler = NULL;
	mbuttonup_handler = NULL;
	rbuttondown_handler = NULL;
	rbuttonup_handler = NULL;
	lbuttondoubleclick_handler = NULL;
	mbuttondoubleclick_handler = NULL;
	rbuttondoubleclick_handler = NULL;
	mousemove_handler = NULL;
	mousewheel_handler = NULL;
	nchittest_handler = NULL;
}

Window::Window(Param &param)
{
	hwnd = NULL;
	pyobj = NULL;
	quit_requested = false;
	active = false;
	creating = true;
	destroying = false;
	native_ref_count = 0;
	memset(&window_frame_size, 0, sizeof(window_frame_size));
	memset(&last_valid_window_rect, 0, sizeof(last_valid_window_rect));
	offscreen_dc = NULL;
	offscreen_bmp = NULL;
	offscreen_size.cx = 0;
	offscreen_size.cy = 0;
	bg_brush = NULL;
	dirty = false;
	frame_pen = NULL;
	caret0_brush = NULL;
	caret1_brush = NULL;
	caret = param.caret;
	caret_blink = 1;
	ime_on = false;
	ime_context = (HIMC)NULL;
	memset(&ime_logfont, 0, sizeof(ime_logfont));
	menu = NULL;
	memset(&caret_rect, 0, sizeof(caret_rect));
	memset(&ime_rect, 0, sizeof(ime_rect));

	ncpaint = param.ncpaint;

	activate_handler = param.activate_handler;
	Py_XINCREF(activate_handler);
	close_handler = param.close_handler;
	Py_XINCREF(close_handler);
	endsession_handler = param.endsession_handler;
	Py_XINCREF(endsession_handler);
	move_handler = param.move_handler;
	Py_XINCREF(move_handler);
	sizing_handler = param.sizing_handler;
	Py_XINCREF(sizing_handler);
	size_handler = param.size_handler;
	Py_XINCREF(size_handler);
	dpi_handler = param.dpi_handler;
	Py_XINCREF(dpi_handler);
	dropfiles_handler = param.dropfiles_handler;
	Py_XINCREF(dropfiles_handler);
	ipc_handler = param.ipc_handler;
	Py_XINCREF(ipc_handler);
	keydown_handler = param.keydown_handler;
	Py_XINCREF(keydown_handler);
	keyup_handler = param.keyup_handler;
	Py_XINCREF(keyup_handler);
	char_handler = param.char_handler;
	Py_XINCREF(char_handler);
	lbuttondown_handler = param.lbuttondown_handler;
	Py_XINCREF(lbuttondown_handler);
	lbuttonup_handler = param.lbuttonup_handler;
	Py_XINCREF(lbuttonup_handler);
	mbuttondown_handler = param.mbuttondown_handler;
	Py_XINCREF(mbuttondown_handler);
	mbuttonup_handler = param.mbuttonup_handler;
	Py_XINCREF(mbuttonup_handler);
	rbuttondown_handler = param.rbuttondown_handler;
	Py_XINCREF(rbuttondown_handler);
	rbuttonup_handler = param.rbuttonup_handler;
	Py_XINCREF(rbuttonup_handler);
	lbuttondoubleclick_handler = param.lbuttondoubleclick_handler;
	Py_XINCREF(lbuttondoubleclick_handler);
	mbuttondoubleclick_handler = param.mbuttondoubleclick_handler;
	Py_XINCREF(mbuttondoubleclick_handler);
	rbuttondoubleclick_handler = param.rbuttondoubleclick_handler;
	Py_XINCREF(rbuttondoubleclick_handler);
	mousemove_handler = param.mousemove_handler;
	Py_XINCREF(mousemove_handler);
	mousewheel_handler = param.mousewheel_handler;
	Py_XINCREF(mousewheel_handler);
	nchittest_handler = param.nchittest_handler;
	Py_XINCREF(nchittest_handler);

	timer_list_ref_count = 0;
	delayed_call_list_ref_count = 0;
	hotkey_list_ref_count = 0;

	if (!bg_brush)
		bg_brush = CreateSolidBrush(param.bg_color);
	if (!frame_pen)
		frame_pen = CreatePen(PS_SOLID, 0, param.frame_color);
	if (!caret0_brush)
		caret0_brush = CreateSolidBrush(param.caret0_color);
	if (!caret1_brush)
		caret1_brush = CreateSolidBrush(param.caret1_color);
}

Window::~Window()
{
	if (pyobj && ((Window_Object *)pyobj)->p == this)
		((Window_Object *)pyobj)->p = NULL;
	clear();

	_clearCallables();

	if (offscreen_dc)
	{
		DeleteDC(offscreen_dc);
		offscreen_dc = NULL;
	}
	if (bg_brush)
	{
		DeleteObject(bg_brush);
		bg_brush = NULL;
	}
	if (frame_pen)
	{
		DeleteObject(frame_pen);
		frame_pen = NULL;
	}
	if (caret0_brush)
	{
		DeleteObject(caret0_brush);
		caret0_brush = NULL;
	}
	if (caret1_brush)
	{
		DeleteObject(caret1_brush);
		caret1_brush = NULL;
	}
	if (offscreen_bmp)
	{
		DeleteObject(offscreen_bmp);
		offscreen_bmp = NULL;
	};

	Py_XDECREF(pyobj);
	pyobj = NULL;
}

Window::Reference::Reference(Window *window) : window(window)
{
	if (window)
		++window->native_ref_count;
}

Window::Reference::~Reference()
{
	if (window && --window->native_ref_count == 0 && !window->creating && window->destroying && !window->hwnd)
		delete window;
}

void Window::SetPyObject(PyObject *_pyobj)
{
	if (pyobj != _pyobj)
	{
		Py_XDECREF(pyobj);
		pyobj = _pyobj;
		Py_XINCREF(pyobj);
	}
}

void Window::appendDirtyRect(const RECT &rect)
{
	if (dirty)
	{
		if (dirty_rect.left > rect.left)
			dirty_rect.left = rect.left;
		if (dirty_rect.top > rect.top)
			dirty_rect.top = rect.top;
		if (dirty_rect.right < rect.right)
			dirty_rect.right = rect.right;
		if (dirty_rect.bottom < rect.bottom)
			dirty_rect.bottom = rect.bottom;
	}
	else
	{
		dirty_rect = rect;
		dirty = true;
	}
}

void Window::clearDirtyRect()
{
	if (dirty)
	{
		dirty = false;
	}
}

void Window::_drawBackground(const RECT &paint_rect)
{
	FillRect(offscreen_dc, &paint_rect, bg_brush);
}

void Window::_drawPlanes(const RECT &paint_rect)
{
	std::list<Plane *>::const_iterator i;
	for (i = plane_list.begin(); i != plane_list.end(); i++)
	{
		Plane *plane = *i;
		plane->Draw(paint_rect);
	}
}

void Window::_drawCaret(const RECT &paint_rect)
{
	if (caret && caret_blink)
	{
		RECT rect;
		IntersectRect(&rect, &paint_rect, &caret_rect);

		if (rect.right > 0 || rect.bottom > 0)
		{
			HGDIOBJ old_brush;
			if (ime_on)
			{
				old_brush = SelectObject(offscreen_dc, caret1_brush);
			}
			else
			{
				old_brush = SelectObject(offscreen_dc, caret0_brush);
			}

			PatBlt(offscreen_dc, rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top, PATINVERT);
			if (old_brush)
				SelectObject(offscreen_dc, old_brush);
		}
	}
}

void Window::flushPaint(HDC hDC, bool bitblt)
{
	if (!dirty)
	{
		return;
	}

	bool dc_need_release = false;
	if (hDC == NULL)
	{
		hDC = GetDC(hwnd);
		dc_need_release = true;
	}
	if (!hDC)
	{
		DWORD error = GetLastError();
		wchar_t message[128];
		swprintf_s(message, L"ckit flushPaint: GetDC failed (WinError %lu)\n", error);
		OutputDebugStringW(message);
		return;
	}

	RECT client_rect;
	GetClientRect(hwnd, &client_rect);

	if (dirty_rect.left < client_rect.left)
		dirty_rect.left = client_rect.left;
	if (dirty_rect.top < client_rect.top)
		dirty_rect.top = client_rect.top;
	if (dirty_rect.right > client_rect.right)
		dirty_rect.right = client_rect.right;
	if (dirty_rect.bottom > client_rect.bottom)
		dirty_rect.bottom = client_rect.bottom;

	// Create or resize the offscreen buffer.
	if (offscreen_dc == NULL || offscreen_bmp == NULL || offscreen_size.cx != client_rect.right - client_rect.left || offscreen_size.cy != client_rect.bottom - client_rect.top)
	{
		if (offscreen_dc)
		{
			DeleteDC(offscreen_dc);
		}
		if (offscreen_bmp)
		{
			DeleteObject(offscreen_bmp);
		}

		int width = client_rect.right - client_rect.left;
		int height = client_rect.bottom - client_rect.top;
		if (width < 1)
		{
			width = 1;
		}
		if (height < 1)
		{
			height = 1;
		}

		// Create the offscreen DC and bitmap.
		offscreen_dc = CreateCompatibleDC(hDC);
		offscreen_bmp = CreateCompatibleBitmap(hDC, width, height);
		SelectObject(offscreen_dc, offscreen_bmp);

		offscreen_size.cx = client_rect.right - client_rect.left;
		offscreen_size.cy = client_rect.bottom - client_rect.top;

		// Redraw everything after creating the offscreen buffer.
		dirty_rect = client_rect;
		FillRect(offscreen_dc, &dirty_rect, bg_brush);
	}

	// Draw into the offscreen buffer.
	{
		IntersectClipRect(offscreen_dc, dirty_rect.left, dirty_rect.top, dirty_rect.right, dirty_rect.bottom);

		_drawBackground(dirty_rect);
		_drawPlanes(dirty_rect);
		_drawCaret(dirty_rect);

		SelectClipRgn(offscreen_dc, NULL);
	}

	// Transfer the offscreen buffer to the window.
	DWORD paint_error = ERROR_SUCCESS;
	const wchar_t *failed_operation = NULL;
	if (bitblt)
	{
		RECT clip_rect;
		int clip = GetClipBox(hDC, &clip_rect);
		if (clip == ERROR)
		{
			paint_error = GetLastError();
			failed_operation = L"GetClipBox";
		}
		else if (clip != NULLREGION && dirty_rect.right > dirty_rect.left && dirty_rect.bottom > dirty_rect.top)
		{
			if (!BitBlt(hDC, dirty_rect.left, dirty_rect.top, dirty_rect.right - dirty_rect.left, dirty_rect.bottom - dirty_rect.top, offscreen_dc, dirty_rect.left, dirty_rect.top, SRCCOPY))
			{
				paint_error = GetLastError();
				failed_operation = L"BitBlt";
			}
		}
	}

	if (dc_need_release)
	{
		ReleaseDC(hwnd, hDC);
	}

	if (failed_operation)
	{
		wchar_t message[128];
		swprintf_s(message, L"ckit flushPaint: %s failed (WinError %lu)\n", failed_operation, paint_error);
		OutputDebugStringW(message);
		return;
	}
	clearDirtyRect();

	if (ime_on)
	{
		_setImePosition();
	}
}

void Window::_onNcPaint(HDC hDC)
{
	RECT window_rect;
	GetWindowRect(hwnd, &window_rect);

	RECT client_rect_local;
	GetClientRect(hwnd, &client_rect_local);

	POINT client_topleft = {0, 0};
	POINT client_bottomright = {client_rect_local.right, client_rect_local.bottom};
	ClientToScreen(hwnd, &client_topleft);
	ClientToScreen(hwnd, &client_bottomright);

	RECT client_rect = {client_topleft.x, client_topleft.y, client_bottomright.x, client_bottomright.y};

	HGDIOBJ old_brush = SelectObject(hDC, bg_brush);
	HGDIOBJ old_pen = SelectObject(hDC, frame_pen);

	// Top.
	RECT rect1 = {
		0,
		0,
		window_rect.right - window_rect.left,
		client_rect.top - window_rect.top};
	FillRect(hDC, &rect1, bg_brush);

	// Left.
	RECT rect2 = {
		0,
		client_rect.top - window_rect.top,
		client_rect.left - window_rect.left,
		client_rect.bottom - window_rect.top};
	FillRect(hDC, &rect2, bg_brush);

	// Right.
	RECT rect3 = {
		client_rect.right - window_rect.left,
		client_rect.top - window_rect.top,
		window_rect.right - window_rect.left,
		client_rect.bottom - window_rect.top};
	FillRect(hDC, &rect3, bg_brush);

	// Bottom.
	RECT rect4 = {
		0,
		client_rect.bottom - window_rect.top,
		window_rect.right - window_rect.left,
		window_rect.bottom - window_rect.top};
	FillRect(hDC, &rect4, bg_brush);

	// Frame outline.
	MoveToEx(hDC, 0, 0, NULL);
	LineTo(hDC, window_rect.right - window_rect.left - 1, 0);
	LineTo(hDC, window_rect.right - window_rect.left - 1, window_rect.bottom - window_rect.top - 1);
	LineTo(hDC, 0, window_rect.bottom - window_rect.top - 1);
	LineTo(hDC, 0, 0);

	if (old_pen)
		SelectObject(hDC, old_pen);
	if (old_brush)
		SelectObject(hDC, old_brush);
}

void Window::_onSizing(DWORD edge, LPRECT rect)
{
	int width = (rect->right - rect->left) - window_frame_size.cx;
	int height = (rect->bottom - rect->top) - window_frame_size.cy;

	if (sizing_handler)
	{
		PyObject *pysize = Py_BuildValue("[ii]", width, height);
		PyObject *pyresult = pysize ? PyObject_CallOneArg(sizing_handler, pysize) : NULL;
		if (pyresult)
		{
			Py_DECREF(pyresult);
			int parsed_width, parsed_height;
			if (PyArg_Parse(pysize, "(ii)", &parsed_width, &parsed_height))
			{
				width = parsed_width;
				height = parsed_height;
			}
			else
			{
				PyErr_Print();
			}
		}
		else
		{
			PyErr_Print();
		}

		Py_XDECREF(pysize);
	}
	if (destroying)
		return;

	width += window_frame_size.cx;
	height += window_frame_size.cy;

	if (edge == WMSZ_LEFT || edge == WMSZ_TOPLEFT || edge == WMSZ_BOTTOMLEFT)
	{
		rect->left = rect->right - width;
	}
	else if (edge == WMSZ_RIGHT || edge == WMSZ_TOPRIGHT || edge == WMSZ_BOTTOMRIGHT)
	{
		rect->right = rect->left + width;
	}

	if (edge == WMSZ_TOP || edge == WMSZ_TOPLEFT || edge == WMSZ_TOPRIGHT)
	{
		rect->top = rect->bottom - height;
	}
	else if (edge == WMSZ_BOTTOM || edge == WMSZ_BOTTOMLEFT || edge == WMSZ_BOTTOMRIGHT)
	{
		rect->bottom = rect->top + height;
	}
}

void Window::_onWindowPositionChange(WINDOWPOS *wndpos, bool send_event)
{
	if (!IsIconic(hwnd))
	{
		::GetWindowRect(hwnd, &last_valid_window_rect);

		if (!(wndpos->flags & SWP_NOMOVE))
		{
			if (send_event && move_handler)
			{
				PyObject *pyarglist = Py_BuildValue("(ii)", wndpos->x, wndpos->y);
				PyObject *pyresult = PyObject_Call(move_handler, pyarglist, NULL);
				Py_DECREF(pyarglist);
				if (pyresult)
				{
					Py_DECREF(pyresult);
				}
				else
				{
					PyErr_Print();
				}
			}
		}

		if (destroying)
			return;

		if (!(wndpos->flags & SWP_NOSIZE))
		{
			_updateWindowFrameRect();

			if (send_event && size_handler)
			{
				RECT client_rect;
				GetClientRect(hwnd, &client_rect);

				PyObject *pyarglist = Py_BuildValue("(ii)", client_rect.right - client_rect.left, client_rect.bottom - client_rect.top);
				PyObject *pyresult = PyObject_Call(size_handler, pyarglist, NULL);
				Py_DECREF(pyarglist);
				if (pyresult)
				{
					Py_DECREF(pyresult);
				}
				else
				{
					PyErr_Print();
				}
			}

			// Redraw after the window size changes.
			if (!destroying)
				InvalidateRect(hwnd, NULL, TRUE);
		}
	}
}

void Window::_updateWindowFrameRect()
{
	// Calculate the difference between the client and window rectangles.
	// AdjustWindowRectEx cannot account for a menu bar wrapping onto multiple rows.

	RECT window_rect;
	if (!GetWindowRect(hwnd, &window_rect))
	{
		return;
	}

	RECT client_rect;
	if (!GetClientRect(hwnd, &client_rect))
	{
		return;
	}

	window_frame_size.cx = (window_rect.right - window_rect.left) - (client_rect.right - client_rect.left);
	window_frame_size.cy = (window_rect.bottom - window_rect.top) - (client_rect.bottom - client_rect.top);
}

void Window::_setImePosition()
{
	HIMC imc = ImmGetContext(hwnd);

	COMPOSITIONFORM cf;

	if (ime_rect.left == 0 && ime_rect.right == 0)
	{
		cf.dwStyle = CFS_POINT;
		cf.ptCurrentPos.x = caret_rect.left;
		cf.ptCurrentPos.y = caret_rect.top;
	}
	else
	{
		cf.dwStyle = CFS_RECT;
		cf.ptCurrentPos.x = caret_rect.left;
		cf.ptCurrentPos.y = caret_rect.top;
		cf.rcArea = ime_rect;
	}

	ImmSetCompositionWindow(imc, &cf);

	ImmReleaseContext(hwnd, imc);
}

void Window::_onTimerCaretBlink()
{
	if (caret_blink > 0)
	{
		--caret_blink;
	}
	else
	{
		caret_blink = 1;
	}

	if (caret_rect.right > 0 && caret_rect.bottom > 0)
	{
		appendDirtyRect(caret_rect);
	}
}

int Window::_getModKey()
{
	int mod = 0;
	if (GetKeyState(VK_MENU) & 0x8000)
		mod |= 1;
	if (GetKeyState(VK_CONTROL) & 0x8000)
		mod |= 2;
	if (GetKeyState(VK_SHIFT) & 0x8000)
		mod |= 4;
	if (GetKeyState(VK_LWIN) & 0x8000)
		mod |= 8;
	if (GetKeyState(VK_RWIN) & 0x8000)
		mod |= 8;
	return mod;
}

void Window::_clearCallables()
{
	Py_XDECREF(activate_handler);
	activate_handler = NULL;
	Py_XDECREF(close_handler);
	close_handler = NULL;
	Py_XDECREF(endsession_handler);
	endsession_handler = NULL;
	Py_XDECREF(move_handler);
	move_handler = NULL;
	Py_XDECREF(sizing_handler);
	sizing_handler = NULL;
	Py_XDECREF(size_handler);
	size_handler = NULL;
	Py_XDECREF(dpi_handler);
	dpi_handler = NULL;
	Py_XDECREF(dropfiles_handler);
	dropfiles_handler = NULL;
	Py_XDECREF(ipc_handler);
	ipc_handler = NULL;
	Py_XDECREF(keydown_handler);
	keydown_handler = NULL;
	Py_XDECREF(keyup_handler);
	keyup_handler = NULL;
	Py_XDECREF(char_handler);
	char_handler = NULL;
	Py_XDECREF(lbuttondown_handler);
	lbuttondown_handler = NULL;
	Py_XDECREF(lbuttonup_handler);
	lbuttonup_handler = NULL;
	Py_XDECREF(mbuttondown_handler);
	mbuttondown_handler = NULL;
	Py_XDECREF(mbuttonup_handler);
	mbuttonup_handler = NULL;
	Py_XDECREF(rbuttondown_handler);
	rbuttondown_handler = NULL;
	Py_XDECREF(rbuttonup_handler);
	rbuttonup_handler = NULL;
	Py_XDECREF(lbuttondoubleclick_handler);
	lbuttondoubleclick_handler = NULL;
	Py_XDECREF(mbuttondoubleclick_handler);
	mbuttondoubleclick_handler = NULL;
	Py_XDECREF(rbuttondoubleclick_handler);
	rbuttondoubleclick_handler = NULL;
	Py_XDECREF(mousemove_handler);
	mousemove_handler = NULL;
	Py_XDECREF(mousewheel_handler);
	mousewheel_handler = NULL;
	Py_CLEAR(nchittest_handler);
	Py_CLEAR(menu);

	for (std::list<TimerInfo>::const_iterator i = timer_list.begin(); i != timer_list.end(); i++)
	{
		Py_XDECREF(i->pyobj);
	}
	timer_list.clear();

	for (std::list<DelayedCallInfo>::const_iterator i = delayed_call_list.begin(); i != delayed_call_list.end(); i++)
	{
		Py_XDECREF(i->pyobj);
	}
	delayed_call_list.clear();

	for (std::list<HotKeyInfo>::const_iterator i = hotkey_list.begin(); i != hotkey_list.end(); i++)
	{
		Py_XDECREF(i->pyobj);
	}
	hotkey_list.clear();

	_clearMenuCommands();
	_clearPopupMenuCommands();
}

void Window::_clearMenuCommands()
{
	for (unsigned int i = 0; i < menu_commands.size(); ++i)
	{
		Py_XDECREF(menu_commands[i]);
	}
	menu_commands.clear();
}

void Window::_clearPopupMenuCommands()
{
	for (unsigned int i = 0; i < popup_menu_commands.size(); ++i)
	{
		Py_XDECREF(popup_menu_commands[i]);
	}
	popup_menu_commands.clear();
}

LRESULT CALLBACK Window::_wndProc(HWND hwnd, UINT msg, WPARAM wp, LPARAM lp)
{
	PythonUtil::GIL_Ensure gil_ensure;
	Window *window = (Window *)GetProp(hwnd, L"ckit_userdata");
	if ((!window && msg != WM_CREATE) || (window && window->destroying && msg != WM_DESTROY))
		return DefWindowProc(hwnd, msg, wp, lp);
	Reference reference(window);

	switch (msg)
	{
	case WM_CREATE:
	{
		CREATESTRUCT *create_data = (CREATESTRUCT *)lp;
		Window *window = (Window *)create_data->lpCreateParams;
		if (!SetProp(hwnd, L"ckit_userdata", window))
			return -1;
		window->hwnd = hwnd;

		window->enableIme(false);

		SetTimer(hwnd, TIMER_PAINT, TIMER_PAINT_INTERVAL, NULL);
		SetTimer(hwnd, TIMER_CARET_BLINK, GetCaretBlinkTime(), NULL);
	}
	break;

	case WM_DESTROY:
	{
		window->destroying = true;
		if (window->pyobj)
			((Window_Object *)window->pyobj)->p = NULL;
		RemoveProp(hwnd, L"ckit_userdata");
		window->hwnd = NULL;

		KillTimer(hwnd, TIMER_PAINT);
		KillTimer(hwnd, TIMER_CARET_BLINK);
		for (std::list<TimerInfo>::const_iterator i = window->timer_list.begin(); i != window->timer_list.end(); ++i)
			if (i->pyobj)
				KillTimer(hwnd, (UINT_PTR)i->pyobj);
		for (std::list<HotKeyInfo>::const_iterator i = window->hotkey_list.begin(); i != window->hotkey_list.end(); ++i)
			if (i->pyobj)
				UnregisterHotKey(hwnd, i->id);

		// Invalidate owned planes now; callback lists survive until all references return.
		window->clear();
	}
	break;

	case WM_CLOSE:
		if (window->close_handler)
		{
			PyObject *pyarglist = Py_BuildValue("()");
			PyObject *pyresult = PyObject_Call(window->close_handler, pyarglist, NULL);
			Py_DECREF(pyarglist);
			if (pyresult)
			{
				Py_DECREF(pyresult);
			}
			else
			{
				PyErr_Print();
			}
		}
		else
		{
			return (DefWindowProc(hwnd, msg, wp, lp));
		}
		break;

	case WM_ACTIVATE:
	{
		switch (LOWORD(wp))
		{
		case WA_ACTIVE:
		case WA_CLICKACTIVE:
			window->active = true;
			break;
		case WA_INACTIVE:
		default:
			window->active = false;
			break;
		}

		if (window->activate_handler)
		{
			PyObject *pyarglist = Py_BuildValue("(i)", window->active);
			PyObject *pyresult = PyObject_Call(window->activate_handler, pyarglist, NULL);
			Py_DECREF(pyarglist);
			if (pyresult)
			{
				Py_DECREF(pyresult);
			}
			else
			{
				PyErr_Print();
			}
		}
	}
	break;

	case WM_INITMENU:
	{
		window->_refreshMenu();
	}
	break;

	case WM_COMMAND:
	{
		int wmId = LOWORD(wp);
		int wmEvent = HIWORD(wp);

		if (ID_MENUITEM <= wmId && wmId < ID_MENUITEM + (int)window->menu_commands.size())
		{
			PyObject *func = window->menu_commands[wmId - ID_MENUITEM];
			if (func)
			{
				PyObject *command_info;
				if (command_info_constructor)
				{
					PyObject *pyarglist2 = Py_BuildValue("()");
					command_info = PyObject_Call(command_info_constructor, pyarglist2, NULL);
					Py_DECREF(pyarglist2);
					if (!command_info)
					{
						PyErr_Print();
						break;
					}
				}
				else
				{
					command_info = Py_None;
					Py_INCREF(command_info);
				}

				PyObject *pyarglist = Py_BuildValue("(O)", command_info);
				Py_DECREF(command_info);
				if (window->destroying)
				{
					Py_DECREF(pyarglist);
					break;
				}
				PyObject *pyresult = PyObject_Call(func, pyarglist, NULL);
				Py_DECREF(pyarglist);
				if (pyresult)
				{
					Py_DECREF(pyresult);
				}
				else
				{
					PyErr_Print();
				}
			}
		}
		else if (ID_POPUP_MENUITEM <= wmId && wmId < ID_POPUP_MENUITEM + (int)window->popup_menu_commands.size())
		{
			PyObject *func = window->popup_menu_commands[wmId - ID_POPUP_MENUITEM];
			if (func)
			{
				PyObject *command_info;
				if (command_info_constructor)
				{
					PyObject *pyarglist2 = Py_BuildValue("()");
					command_info = PyObject_Call(command_info_constructor, pyarglist2, NULL);
					Py_DECREF(pyarglist2);
					if (!command_info)
					{
						PyErr_Print();
						break;
					}
				}
				else
				{
					command_info = Py_None;
					Py_INCREF(command_info);
				}

				PyObject *pyarglist = Py_BuildValue("(O)", command_info);
				Py_DECREF(command_info);
				if (window->destroying)
				{
					Py_DECREF(pyarglist);
					break;
				}
				PyObject *pyresult = PyObject_Call(func, pyarglist, NULL);
				Py_DECREF(pyarglist);
				if (pyresult)
				{
					Py_DECREF(pyresult);
				}
				else
				{
					PyErr_Print();
				}
			}
		}
		else
		{
			return DefWindowProc(hwnd, msg, wp, lp);
		}
	}
	break;

	case WM_TIMER:
	{
		if (wp == TIMER_PAINT)
		{
			window->flushPaint();

			if (window->delayed_call_list.size())
			{
				window->delayed_call_list_ref_count++;

				for (std::list<DelayedCallInfo>::iterator i = window->delayed_call_list.begin(); !window->destroying && i != window->delayed_call_list.end(); i++)
				{
					if (i->pyobj)
					{
						i->timeout -= TIMER_PAINT_INTERVAL;
						if (i->timeout <= 0)
						{
							// Clear the callback before invoking it to prevent nested calls.
							PyObject *pyobj = i->pyobj;
							i->pyobj = NULL;

							PyObject *pyarglist = Py_BuildValue("()");
							PyObject *pyresult = PyObject_Call(pyobj, pyarglist, NULL);
							Py_DECREF(pyarglist);
							if (pyresult)
							{
								Py_DECREF(pyresult);
							}
							else
							{
								PyErr_Print();
							}

							Py_XDECREF(pyobj);
						}
					}
				}

				window->delayed_call_list_ref_count--;

				// Remove invalidated nodes.
				if (window->delayed_call_list_ref_count == 0)
				{
					for (std::list<DelayedCallInfo>::iterator i = window->delayed_call_list.begin(); i != window->delayed_call_list.end();)
					{
						if ((i->pyobj) == 0)
						{
							i = window->delayed_call_list.erase(i);
						}
						else
						{
							i++;
						}
					}
				}
			}
		}
		else if (wp == TIMER_CARET_BLINK)
		{
			window->_onTimerCaretBlink();
			window->flushPaint();
		}
		else
		{
			if (!window->quit_requested)
			{
				window->timer_list_ref_count++;

				for (std::list<TimerInfo>::iterator i = window->timer_list.begin(); i != window->timer_list.end(); i++)
				{
					if (wp == (WPARAM)i->pyobj)
					{
						if (i->calling)
							continue;

						i->calling = true;

						PyObject *pyarglist = Py_BuildValue("()");
						PyObject *pyresult = PyObject_Call((i->pyobj), pyarglist, NULL);
						Py_DECREF(pyarglist);
						if (pyresult)
						{
							Py_DECREF(pyresult);
						}
						else
						{
							if (PyErr_Occurred() == PyExc_KeyboardInterrupt)
							{
								printf("KeyboardInterrupt\n");
								exit(0);
							}

							PyErr_Print();
						}

						i->calling = false;

						break;
					}
				}

				window->timer_list_ref_count--;

				// Remove invalidated nodes.
				if (window->timer_list_ref_count == 0)
				{
					for (std::list<TimerInfo>::iterator i = window->timer_list.begin(); i != window->timer_list.end();)
					{
						if ((i->pyobj) == 0)
						{
							i = window->timer_list.erase(i);
						}
						else
						{
							i++;
						}
					}
				}
			}
		}
	}
	break;

	case WM_HOTKEY:
		if (!window->quit_requested)
		{
			window->hotkey_list_ref_count++;

			for (std::list<HotKeyInfo>::iterator i = window->hotkey_list.begin(); i != window->hotkey_list.end(); i++)
			{
				if (wp == i->id && i->pyobj != NULL)
				{
					if (i->calling)
						continue;

					i->calling = true;

					PyObject *pyarglist = Py_BuildValue("()");
					PyObject *pyresult = PyObject_Call(i->pyobj, pyarglist, NULL);
					Py_DECREF(pyarglist);
					if (pyresult)
					{
						Py_DECREF(pyresult);
					}
					else
					{
						PyErr_Print();
					}

					i->calling = false;

					break;
				}
			}

			window->hotkey_list_ref_count--;

			// Remove invalidated nodes.
			if (window->hotkey_list_ref_count == 0)
			{
				for (std::list<HotKeyInfo>::iterator i = window->hotkey_list.begin(); i != window->hotkey_list.end();)
				{
					if (i->pyobj == 0)
					{
						i = window->hotkey_list.erase(i);
					}
					else
					{
						i++;
					}
				}
			}
		}
		break;

	case WM_ERASEBKGND:
		break;

	case WM_PAINT:
	{
		PAINTSTRUCT ps;
		HDC hDC = BeginPaint(hwnd, &ps);

		BitBlt(
			hDC,
			ps.rcPaint.left,
			ps.rcPaint.top,
			ps.rcPaint.right - ps.rcPaint.left,
			ps.rcPaint.bottom - ps.rcPaint.top,
			window->offscreen_dc,
			ps.rcPaint.left,
			ps.rcPaint.top,
			SRCCOPY);

		EndPaint(hwnd, &ps);
	}
	break;

	case WM_SIZING:
		window->_onSizing((DWORD)wp, (LPRECT)lp);
		break;

	case WM_WINDOWPOSCHANGING:
		window->_onWindowPositionChange((WINDOWPOS *)lp, false);
		break;

	case WM_WINDOWPOSCHANGED:
		window->_onWindowPositionChange((WINDOWPOS *)lp, true);
		break;

	case WM_DPICHANGED:
	case WM_DISPLAYCHANGE:
	case WM_SETTINGCHANGE:
	{
		if (msg == WM_SETTINGCHANGE && wp != SPI_SETWORKAREA)
			break;
		int dpi = msg == WM_DPICHANGED ? HIWORD(wp) : GetDpiForWindow(hwnd);
		float scale = (float)dpi / USER_DEFAULT_SCREEN_DPI;

		if (window->dpi_handler)
		{
			PyObject *pyarglist = Py_BuildValue("(f)", scale);
			PyObject *pyresult = PyObject_Call(window->dpi_handler, pyarglist, NULL);
			Py_DECREF(pyarglist);
			if (pyresult)
			{
				Py_DECREF(pyresult);
			}
			else
			{
				PyErr_Print();
			}
		}
	}
	break;

	case WM_LBUTTONDOWN:
		if (window->lbuttondown_handler)
		{
			int mod = _getModKey();

			PyObject *pyarglist = Py_BuildValue("(iii)", (short)LOWORD(lp), (short)HIWORD(lp), mod);
			PyObject *pyresult = PyObject_Call(window->lbuttondown_handler, pyarglist, NULL);
			Py_DECREF(pyarglist);
			if (pyresult)
			{
				Py_DECREF(pyresult);
			}
			else
			{
				PyErr_Print();
			}
		}
		break;

	case WM_LBUTTONUP:
		if (window->lbuttonup_handler)
		{
			int mod = _getModKey();

			PyObject *pyarglist = Py_BuildValue("(iii)", (short)LOWORD(lp), (short)HIWORD(lp), mod);
			PyObject *pyresult = PyObject_Call(window->lbuttonup_handler, pyarglist, NULL);
			Py_DECREF(pyarglist);
			if (pyresult)
			{
				Py_DECREF(pyresult);
			}
			else
			{
				PyErr_Print();
			}
		}
		break;

	case WM_MBUTTONDOWN:
		if (window->mbuttondown_handler)
		{
			int mod = _getModKey();

			PyObject *pyarglist = Py_BuildValue("(iii)", (short)LOWORD(lp), (short)HIWORD(lp), mod);
			PyObject *pyresult = PyObject_Call(window->mbuttondown_handler, pyarglist, NULL);
			Py_DECREF(pyarglist);
			if (pyresult)
			{
				Py_DECREF(pyresult);
			}
			else
			{
				PyErr_Print();
			}
		}
		break;

	case WM_MBUTTONUP:
		if (window->mbuttonup_handler)
		{
			int mod = _getModKey();

			PyObject *pyarglist = Py_BuildValue("(iii)", (short)LOWORD(lp), (short)HIWORD(lp), mod);
			PyObject *pyresult = PyObject_Call(window->mbuttonup_handler, pyarglist, NULL);
			Py_DECREF(pyarglist);
			if (pyresult)
			{
				Py_DECREF(pyresult);
			}
			else
			{
				PyErr_Print();
			}
		}
		break;

	case WM_RBUTTONDOWN:
		if (window->rbuttondown_handler)
		{
			int mod = _getModKey();

			PyObject *pyarglist = Py_BuildValue("(iii)", (short)LOWORD(lp), (short)HIWORD(lp), mod);
			PyObject *pyresult = PyObject_Call(window->rbuttondown_handler, pyarglist, NULL);
			Py_DECREF(pyarglist);
			if (pyresult)
			{
				Py_DECREF(pyresult);
			}
			else
			{
				PyErr_Print();
			}
		}
		break;

	case WM_RBUTTONUP:
		if (window->rbuttonup_handler)
		{
			int mod = _getModKey();

			PyObject *pyarglist = Py_BuildValue("(iii)", (short)LOWORD(lp), (short)HIWORD(lp), mod);
			PyObject *pyresult = PyObject_Call(window->rbuttonup_handler, pyarglist, NULL);
			Py_DECREF(pyarglist);
			if (pyresult)
			{
				Py_DECREF(pyresult);
			}
			else
			{
				PyErr_Print();
			}
		}
		break;

	case WM_LBUTTONDBLCLK:
		if (window->lbuttondoubleclick_handler)
		{
			int mod = _getModKey();

			PyObject *pyarglist = Py_BuildValue("(iii)", (short)LOWORD(lp), (short)HIWORD(lp), mod);
			PyObject *pyresult = PyObject_Call(window->lbuttondoubleclick_handler, pyarglist, NULL);
			Py_DECREF(pyarglist);
			if (pyresult)
			{
				Py_DECREF(pyresult);
			}
			else
			{
				PyErr_Print();
			}
		}
		break;

	case WM_MBUTTONDBLCLK:
		if (window->mbuttondoubleclick_handler)
		{
			int mod = _getModKey();

			PyObject *pyarglist = Py_BuildValue("(iii)", (short)LOWORD(lp), (short)HIWORD(lp), mod);
			PyObject *pyresult = PyObject_Call(window->mbuttondoubleclick_handler, pyarglist, NULL);
			Py_DECREF(pyarglist);
			if (pyresult)
			{
				Py_DECREF(pyresult);
			}
			else
			{
				PyErr_Print();
			}
		}
		break;

	case WM_RBUTTONDBLCLK:
		if (window->rbuttondoubleclick_handler)
		{
			int mod = _getModKey();

			PyObject *pyarglist = Py_BuildValue("(iii)", (short)LOWORD(lp), (short)HIWORD(lp), mod);
			PyObject *pyresult = PyObject_Call(window->rbuttondoubleclick_handler, pyarglist, NULL);
			Py_DECREF(pyarglist);
			if (pyresult)
			{
				Py_DECREF(pyresult);
			}
			else
			{
				PyErr_Print();
			}
		}
		break;

	case WM_MOUSEMOVE:
		if (window->mousemove_handler)
		{
			int mod = _getModKey();

			PyObject *pyarglist = Py_BuildValue("(iii)", (short)LOWORD(lp), (short)HIWORD(lp), mod);
			PyObject *pyresult = PyObject_Call(window->mousemove_handler, pyarglist, NULL);
			Py_DECREF(pyarglist);
			if (pyresult)
			{
				Py_DECREF(pyresult);
			}
			else
			{
				PyErr_Print();
			}
		}
		break;

	case WM_MOUSEWHEEL:
		if (window->mousewheel_handler)
		{
			int mod = _getModKey();

			PyObject *pyarglist = Py_BuildValue("(iifi)", (short)LOWORD(lp), (short)HIWORD(lp), (float)GET_WHEEL_DELTA_WPARAM(wp) / WHEEL_DELTA, mod);
			PyObject *pyresult = PyObject_Call(window->mousewheel_handler, pyarglist, NULL);
			Py_DECREF(pyarglist);
			if (pyresult)
			{
				Py_DECREF(pyresult);
			}
			else
			{
				PyErr_Print();
			}
		}
		break;

	case WM_DROPFILES:
	{
		PyObject *pyfiles = PyList_New(0);

		HDROP drop = (HDROP)wp;
		POINT point = {};
		UINT num_items = DragQueryFileW(drop, 0xFFFFFFFF, NULL, 0);
		for (UINT i = 0; pyfiles && i < num_items; ++i)
		{
			UINT length = DragQueryFileW(drop, i, NULL, 0);
			if (!length || length == UINT_MAX)
			{
				PyErr_SetString(PyExc_ValueError, "Invalid dropped path length.");
				break;
			}
			wchar_t *path = (wchar_t *)PyMem_Calloc((size_t)length + 1, sizeof(wchar_t));
			if (!path)
			{
				PyErr_NoMemory();
				break;
			}
			UINT copied = DragQueryFileW(drop, i, path, length + 1);
			if (copied != length)
			{
				PyMem_Free(path);
				PyErr_SetString(PyExc_ValueError, "Failed to retrieve the complete dropped path.");
				break;
			}

			PyObject *pyitem = PyUnicode_FromWideChar(path, copied);
			PyMem_Free(path);
			if (!pyitem)
				break;
			int appended = PyList_Append(pyfiles, pyitem);
			Py_DECREF(pyitem);
			if (appended < 0)
				break;
		}
		DragQueryPoint(drop, &point);
		DragFinish(drop);
		if (PyErr_Occurred())
		{
			Py_XDECREF(pyfiles);
			PyErr_Print();
			break;
		}

		if (window->dropfiles_handler)
		{
			PyObject *pyarglist = Py_BuildValue("(iiO)", point.x, point.y, pyfiles);
			PyObject *pyresult = pyarglist ? PyObject_Call(window->dropfiles_handler, pyarglist, NULL) : NULL;
			Py_XDECREF(pyarglist);
			if (pyresult)
			{
				Py_DECREF(pyresult);
			}
			else
			{
				PyErr_Print();
			}
		}
		Py_DECREF(pyfiles);
	}
	break;

	case WM_COPYDATA:
	{
		COPYDATASTRUCT *data = (COPYDATASTRUCT *)lp;
		if (!data)
		{
			PyErr_SetString(PyExc_ValueError, "WM_COPYDATA requires a COPYDATASTRUCT.");
			PyErr_Print();
			return FALSE;
		}

		if (data->dwData == 0x101 && window->ipc_handler)
		{
			if (data->cbData && !data->lpData)
			{
				PyErr_SetString(PyExc_ValueError, "WM_COPYDATA payload is NULL with a nonzero size.");
				PyErr_Print();
				return FALSE;
			}
			PyObject *pyarglist = Py_BuildValue("(s#)", data->cbData ? (const char *)data->lpData : "", (Py_ssize_t)data->cbData);
			if (!pyarglist)
			{
				PyErr_Print();
				return FALSE;
			}
			PyObject *pyresult = PyObject_Call(window->ipc_handler, pyarglist, NULL);
			Py_DECREF(pyarglist);
			if (pyresult)
			{
				Py_DECREF(pyresult);
			}
			else
			{
				PyErr_Print();
				return FALSE;
			}
		}
	}
	break;

	case WM_IME_STARTCOMPOSITION:
		window->_setImePosition();
		return (DefWindowProc(hwnd, msg, wp, lp));

	case WM_IME_NOTIFY:
		if (wp == IMN_SETOPENSTATUS)
		{
			HIMC imc = ImmGetContext(hwnd);
			window->ime_on = ImmGetOpenStatus(imc) != FALSE;
			ImmReleaseContext(hwnd, imc);

			// FIXME: Limit redrawing to the caret area.
			InvalidateRect(hwnd, NULL, TRUE);
		}
		return (DefWindowProc(hwnd, msg, wp, lp));

	case WM_VSCROLL:
		break;

	case WM_KEYDOWN:
	case WM_SYSKEYDOWN:
		if (window->keydown_handler)
		{
			INT_PTR vk = wp;
			int mod = _getModKey();

			PyObject *pyarglist = Py_BuildValue("(ii)", vk, mod);
			PyObject *pyresult = PyObject_Call(window->keydown_handler, pyarglist, NULL);
			Py_DECREF(pyarglist);
			if (pyresult)
			{
				Py_DECREF(pyresult);
			}
			else
			{
				PyErr_Print();
			}
		}
		break;

	case WM_KEYUP:
	case WM_SYSKEYUP:
		if (window->keyup_handler)
		{
			INT_PTR vk = wp;
			int mod = _getModKey();

			PyObject *pyarglist = Py_BuildValue("(ii)", vk, mod);
			PyObject *pyresult = PyObject_Call(window->keyup_handler, pyarglist, NULL);
			Py_DECREF(pyarglist);
			if (pyresult)
			{
				Py_DECREF(pyresult);
			}
			else
			{
				PyErr_Print();
			}
		}
		break;

	case WM_CHAR:
	case WM_IME_CHAR:
		if (window->char_handler)
		{
			INT_PTR ch = wp;
			int mod = _getModKey();

			PyObject *pyarglist = Py_BuildValue("(ii)", ch, mod);
			PyObject *pyresult = PyObject_Call(window->char_handler, pyarglist, NULL);
			Py_DECREF(pyarglist);
			if (pyresult)
			{
				Py_DECREF(pyresult);
			}
			else
			{
				PyErr_Print();
			}
		}
		break;

	case WM_ENDSESSION:
		if (wp)
		{
			if (window->endsession_handler)
			{
				PyObject *pyarglist = Py_BuildValue("()");
				PyObject *pyresult = PyObject_Call(window->endsession_handler, pyarglist, NULL);
				Py_DECREF(pyarglist);
				if (pyresult)
				{
					Py_DECREF(pyresult);
				}
				else
				{
					PyErr_Print();
				}
			}
		}
		return 0;

	case WM_NCPAINT:
		if (window->ncpaint)
		{
			HDC hdc = GetWindowDC(hwnd);
			window->_onNcPaint(hdc);
			ReleaseDC(hwnd, hdc);
			return 0;
		}
		else
		{
			return (DefWindowProc(hwnd, msg, wp, lp));
		}

	case WM_NCHITTEST:
		if (window->nchittest_handler)
		{
			PyObject *pyarglist = Py_BuildValue("(ii)", (short)LOWORD(lp), (short)HIWORD(lp));
			if (!pyarglist)
			{
				PyErr_Print();
				return DefWindowProc(hwnd, msg, wp, lp);
			}
			PyObject *pyresult = PyObject_Call(window->nchittest_handler, pyarglist, NULL);
			Py_DECREF(pyarglist);
			if (pyresult)
			{
				int result;
				int parsed = PyArg_Parse(pyresult, "i", &result);
				Py_DECREF(pyresult);
				if (parsed)
				{
					return result;
				}
				PyErr_Print();
			}
			else
			{
				PyErr_Print();
			}
		}

	default:
		return (DefWindowProc(hwnd, msg, wp, lp));
	}

	return (1);
}

bool Window::_registerWindowClass()
{
	HINSTANCE hInstance = GetModuleHandle(NULL);

	WNDCLASSEX wc;
	memset(&wc, 0, sizeof(wc));
	wc.cbSize = sizeof(wc);
	wc.style = CS_DBLCLKS;
	wc.lpfnWndProc = _wndProc;
	wc.cbClsExtra = 0;
	wc.cbWndExtra = 0;
	wc.hInstance = hInstance;
	wc.hIcon = LoadIcon(hInstance, (const wchar_t *)1);
	wc.hCursor = LoadCursor(NULL, IDC_ARROW);
	wc.hbrBackground = CreateSolidBrush(RGB(0x00, 0x00, 0x00));
	wc.lpszMenuName = NULL;
	wc.lpszClassName = WINDOW_CLASS_NAME.c_str();
	wc.hIconSm = (HICON)LoadImage(hInstance, (const wchar_t *)1, IMAGE_ICON, 16, 16, 0);
	if (!wc.hIconSm)
		wc.hIconSm = wc.hIcon;

	if (!RegisterClassEx(&wc))
	{
		printf("RegisterClassEx failed\n");
		return (FALSE);
	}

	return (TRUE);
}

bool Window::_createWindow(Param &param)
{
	HINSTANCE hInstance = GetModuleHandle(NULL);
	style = WS_OVERLAPPED | WS_CLIPCHILDREN | WS_POPUP;
	exstyle = WS_EX_ACCEPTFILES;
	LONG w, h;
	LONG posx, posy;

	if (param.is_transparent_color_given || (param.is_transparency_given))
	{
		exstyle |= WS_EX_LAYERED;
	}

	if (param.is_top_most)
	{
		exstyle |= WS_EX_TOPMOST;
	}

	if (param.title_bar)
	{
		style |= WS_CAPTION;
	}

	if (param.resizable)
	{
		style |= WS_THICKFRAME;
	}
	else if (!param.noframe)
	{
		exstyle |= WS_EX_DLGMODALFRAME;
	}

	if (param.minimizebox)
	{
		style |= WS_MINIMIZEBOX;
	}

	if (param.maximizebox && param.resizable)
	{
		style |= WS_MAXIMIZEBOX;
	}

	if (param.sysmenu)
	{
		style |= WS_SYSMENU;
	}

	if (param.tool)
	{
		exstyle |= WS_EX_TOOLWINDOW;
	}

	int dpi = getDpiFromPosition(param.winpos_x, param.winpos_y);

	RECT window_frame_rect;
	memset(&window_frame_rect, 0, sizeof(window_frame_rect));
	AdjustWindowRectExForDpi(&window_frame_rect, style, (menu != NULL), exstyle, dpi);
	window_frame_size.cx = window_frame_rect.right - window_frame_rect.left;
	window_frame_size.cy = window_frame_rect.bottom - window_frame_rect.top;

	w = param.winsize_w + window_frame_size.cx;
	h = param.winsize_h + window_frame_size.cy;

	if (param.is_winpos_given)
	{
		posx = param.winpos_x;
		posy = param.winpos_y;

		if (param.origin & ORIGIN_X_CENTER)
		{
			posx -= w / 2;
		}
		else if (param.origin & ORIGIN_X_RIGHT)
		{
			posx -= w;
		}

		if (param.origin & ORIGIN_Y_CENTER)
		{
			posy -= h / 2;
		}
		else if (param.origin & ORIGIN_Y_BOTTOM)
		{
			posy -= h;
		}
	}
	else
	{
		posx = CW_USEDEFAULT;
		posy = CW_USEDEFAULT;
	}

	// Use per-monitor awareness to disable automatic non-client DPI scaling without a DPI handler.
	DPI_AWARENESS_CONTEXT original_dpi_aware_context = 0;
	if (!dpi_handler)
	{
		original_dpi_aware_context = SetThreadDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE);
	}

	SetLastError(ERROR_SUCCESS);
	HWND created_hwnd = CreateWindowEx(exstyle, WINDOW_CLASS_NAME.c_str(), param.title.c_str(), style,
				   posx, posy, w, h,
				   param.parent_window_hwnd, NULL, hInstance, this);
	DWORD create_error = created_hwnd ? ERROR_SUCCESS : GetLastError();

	// Restore the thread's DPI awareness.
	if (!dpi_handler)
	{
		SetThreadDpiAwarenessContext(original_dpi_aware_context);
	}

	if (!created_hwnd || !hwnd)
	{
		hwnd = NULL;
		PyErr_SetFromWindowsErr(create_error ? create_error : ERROR_GEN_FAILURE);
		return (FALSE);
	}

	if (param.is_transparency_given)
	{
		SetLayeredWindowAttributes(hwnd, 0, param.transparency, LWA_ALPHA);
	}
	else if (param.is_transparent_color_given)
	{
		SetLayeredWindowAttributes(hwnd, param.transparent_color, 255, LWA_COLORKEY);
	}

	if (param.show)
	{
		show(true, true);
	}
	if (!hwnd)
	{
		PyErr_SetString(PyExc_RuntimeError, "window destroyed during creation.");
		return false;
	}

	return (TRUE);
}

static int CALLBACK cbEnumFont(
	ENUMLOGFONTEX *lpelfe,	 // Logical font data.
	NEWTEXTMETRICEX *lpntme, // Physical font metrics.
	DWORD FontType,			 // Font type.
	LPARAM lParam			 // Application-defined data.
)
{
	if ((lpelfe->elfLogFont.lfPitchAndFamily & FIXED_PITCH) == 0)
		return 1;
	if (lpelfe->elfLogFont.lfFaceName[0] == '@')
		return 1;

	std::vector<std::wstring> &font_list = *((std::vector<std::wstring> *)lParam);

	for (std::vector<std::wstring>::const_iterator i = font_list.begin(); i != font_list.end(); i++)
	{
		if (*i == lpelfe->elfLogFont.lfFaceName)
			return 1;
	}

	font_list.push_back(lpelfe->elfLogFont.lfFaceName);

	return 1;
}

void Window::enumFonts(std::vector<std::wstring> *font_list)
{
	HDC hdc = GetDC(NULL);

	EnumFontFamiliesEx(
		hdc,
		NULL,
		(FONTENUMPROC)cbEnumFont,
		(LPARAM)font_list,
		0);

	ReleaseDC(NULL, hdc);
}

void Window::setBGColor(COLORREF color)
{
	if (bg_brush)
	{
		DeleteObject(bg_brush);
	}
	bg_brush = CreateSolidBrush(color);

	RECT dirty_rect;
	GetClientRect(hwnd, &dirty_rect);
	appendDirtyRect(dirty_rect);

	RedrawWindow(hwnd, NULL, NULL, RDW_FRAME | RDW_INVALIDATE);
}

void Window::setFrameColor(COLORREF color)
{
	if (frame_pen)
	{
		DeleteObject(frame_pen);
	}
	frame_pen = CreatePen(PS_SOLID, 0, color);

	RedrawWindow(hwnd, NULL, NULL, RDW_FRAME | RDW_INVALIDATE);
}

void Window::setCaretColor(COLORREF color0, COLORREF color1)
{
	if (caret0_brush)
	{
		DeleteObject(caret0_brush);
	}
	if (caret1_brush)
	{
		DeleteObject(caret1_brush);
	}

	caret0_brush = CreateSolidBrush(color0);
	caret1_brush = CreateSolidBrush(color1);

	appendDirtyRect(caret_rect);
}

void Window::_buildMenu(HMENU menu_handle, PyObject *pysequence, int depth, bool parent_enabled)
{
	if (!destroying && pysequence && PySequence_Check(pysequence))
	{
		Py_ssize_t num_items = PySequence_Length(pysequence);
		if (num_items < 0)
		{
			PyErr_Print();
			return;
		}
		for (Py_ssize_t i = 0; !destroying && i < num_items; ++i)
		{
			PyObject *pychild_node = PySequence_GetItem(pysequence, i);
			if (!pychild_node)
			{
				PyErr_Print();
				return;
			}

			bool enabled = parent_enabled;
			if (destroying)
				goto cont;

			if (MenuNode_Check(pychild_node))
			{
				MenuNode *child_node = ((MenuNode_Object *)pychild_node)->p;

				UINT flags = 0;

				if (depth && child_node->visible)
				{
					PyObject *pyresult = PyObject_CallNoArgs(child_node->visible);
					if (pyresult)
					{
						int result;
						int parsed = PyArg_Parse(pyresult, "i", &result);
						Py_DECREF(pyresult);
						if (!parsed)
						{
							PyErr_Print();
						}

						if (parsed && !result)
						{
							goto cont;
						}
					}
					else
					{
						PyErr_Print();
					}
				}

				if (destroying)
					goto cont;

				if (enabled)
				{
					if (child_node->enabled)
					{
						PyObject *pyresult = PyObject_CallNoArgs(child_node->enabled);
						if (pyresult)
						{
							int result;
							int parsed = PyArg_Parse(pyresult, "i", &result);
							Py_DECREF(pyresult);
							if (!parsed)
							{
								PyErr_Print();
							}

							if (parsed && !result)
							{
								enabled = false;

								if (depth)
								{
									flags |= MF_DISABLED | MF_GRAYED;
								}
							}
						}
						else
						{
							PyErr_Print();
						}
					}
				}
				else
				{
					if (depth)
					{
						flags |= MF_DISABLED | MF_GRAYED;
					}
				}

				if (destroying)
					goto cont;

				if (depth && child_node->checked)
				{
					PyObject *pyresult = PyObject_CallNoArgs(child_node->checked);
					if (pyresult)
					{
						int result;
						int parsed = PyArg_Parse(pyresult, "i", &result);
						Py_DECREF(pyresult);
						if (!parsed)
						{
							PyErr_Print();
						}

						if (parsed && result)
						{
							flags |= MF_CHECKED;
						}
						else
						{
							flags |= MF_UNCHECKED;
						}
					}
					else
					{
						PyErr_Print();
					}
				}

				if (destroying)
					goto cont;

				if (depth && child_node->separator)
				{
					AppendMenu(menu_handle, MF_SEPARATOR, 0, L"");
				}
				else if (child_node->items)
				{
					HMENU child_menu_handle = CreateMenu();

					_buildMenu(child_menu_handle, child_node->items, depth + 1, enabled);
					if (destroying)
					{
						DestroyMenu(child_menu_handle);
						goto cont;
					}

					AppendMenu(menu_handle, flags | MF_POPUP, (UINT_PTR)child_menu_handle, child_node->text.c_str());
				}
				else if (depth && child_node->command)
				{
					if (ID_MENUITEM + menu_commands.size() > ID_MENUITEM_MAX)
					{
						goto cont;
					}

					AppendMenu(menu_handle, flags, ID_MENUITEM + menu_commands.size(), child_node->text.c_str());

					menu_commands.push_back(child_node->command);
					Py_INCREF(child_node->command);
				}
			}
			else if (depth && PyCallable_Check(pychild_node))
			{
				PyObject *pyresult = PyObject_CallNoArgs(pychild_node);
				if (pyresult)
				{
					_buildMenu(menu_handle, pyresult, depth, enabled);

					Py_DECREF(pyresult);
				}
				else
				{
					PyErr_Print();
				}
			}

		cont:

			Py_XDECREF(pychild_node);
		}
	}
}

void Window::setMenu(PyObject *_menu)
{
	Reference reference(this);
	if (menu == _menu)
		return;

	Py_XDECREF(menu);
	menu = _menu;
	Py_XINCREF(menu);

	HMENU old_menu_handle = GetMenu(hwnd);

	_clearMenuCommands();
	if (destroying)
		return;

	// Rebuild the menu from MenuNode.
	if (menu)
	{
		HMENU menu_handle = CreateMenu();

		if (MenuNode_Check(menu))
		{
			_buildMenu(menu_handle, ((MenuNode_Object *)menu)->p->items, 0, true);
		}

		if (destroying)
		{
			DestroyMenu(menu_handle);
			return;
		}
		SetMenu(hwnd, menu_handle);
	}
	else
	{
		SetMenu(hwnd, NULL);
	}

	// Destroy the old menu.
	if (old_menu_handle)
	{
		DestroyMenu(old_menu_handle);
	}

	if (!destroying)
		_updateWindowFrameRect();
}

void Window::_refreshMenu()
{
	_clearMenuCommands();
	if (destroying)
		return;

	// Rebuild the menu from MenuNode.
	if (menu)
	{
		HMENU menu_handle = GetMenu(hwnd);

		// Clear the menu.
		while (true)
		{
			if (!DeleteMenu(menu_handle, 0, MF_BYPOSITION))
			{
				break;
			}
		}

		if (MenuNode_Check(menu))
		{
			bool menu_enabled = true;
			if (((MenuNode_Object *)menu)->p->enabled)
			{
				PyObject *pyresult = PyObject_CallNoArgs(((MenuNode_Object *)menu)->p->enabled);
				if (pyresult)
				{
					int result;
					int parsed = PyArg_Parse(pyresult, "i", &result);
					Py_DECREF(pyresult);
					if (!parsed)
					{
						PyErr_Print();
					}

					if (parsed && !result)
					{
						menu_enabled = false;
					}
				}
				else
				{
					PyErr_Print();
				}
			}

			_buildMenu(menu_handle, ((MenuNode_Object *)menu)->p->items, 0, menu_enabled);
		}

		if (!destroying)
			DrawMenuBar(hwnd);
	}
}

void Window::setPositionAndSize(int x, int y, int width, int height, int origin)
{
	Reference reference(this);
	int client_w = width;
	int client_h = height;

	for (int i = 0; i < 2; i++)
	{
		_updateWindowFrameRect();

		int window_x = x;
		int window_y = y;
		int window_w = client_w + window_frame_size.cx;
		int window_h = client_h + window_frame_size.cy;

		if (origin & ORIGIN_X_CENTER)
		{
			window_x -= window_w / 2;
		}
		else if (origin & ORIGIN_X_RIGHT)
		{
			window_x -= window_w;
		}

		if (origin & ORIGIN_Y_CENTER)
		{
			window_y -= window_h / 2;
		}
		else if (origin & ORIGIN_Y_BOTTOM)
		{
			window_y -= window_h;
		}

		::SetWindowPos(hwnd, NULL, window_x, window_y, window_w, window_h, SWP_NOZORDER | SWP_NOACTIVATE);
		if (destroying)
			return;

		// Non-client DPI scaling can make SetWindowPos produce an unexpected client size.
		// Check the resulting client size and retry if necessary.
		RECT client_rect;
		::GetClientRect(hwnd, &client_rect);
		if (client_rect.right - client_rect.left == client_w && client_rect.bottom - client_rect.top == client_h)
		{
			break;
		}
	}

	RECT dirty_rect = {0, 0, client_w, client_h};
	appendDirtyRect(dirty_rect);
}

void Window::setCapture()
{
	SetCapture(hwnd);
}

void Window::releaseCapture()
{
	if (hwnd != GetCapture())
	{
		return;
	}
	ReleaseCapture();
}

void Window::setMouseCursor(int id)
{
	LPCTSTR idc;

	switch (id)
	{
	case MOUSE_CURSOR_APPSTARTING:
		idc = IDC_APPSTARTING;
		break;
	case MOUSE_CURSOR_ARROW:
		idc = IDC_ARROW;
		break;
	case MOUSE_CURSOR_CROSS:
		idc = IDC_CROSS;
		break;
	case MOUSE_CURSOR_HAND:
		idc = IDC_HAND;
		break;
	case MOUSE_CURSOR_HELP:
		idc = IDC_HELP;
		break;
	case MOUSE_CURSOR_IBEAM:
		idc = IDC_IBEAM;
		break;
	case MOUSE_CURSOR_NO:
		idc = IDC_NO;
		break;
	case MOUSE_CURSOR_SIZEALL:
		idc = IDC_SIZEALL;
		break;
	case MOUSE_CURSOR_SIZENESW:
		idc = IDC_SIZENESW;
		break;
	case MOUSE_CURSOR_SIZENS:
		idc = IDC_SIZENS;
		break;
	case MOUSE_CURSOR_SIZENWSE:
		idc = IDC_SIZENWSE;
		break;
	case MOUSE_CURSOR_SIZEWE:
		idc = IDC_SIZEWE;
		break;
	case MOUSE_CURSOR_UPARROW:
		idc = IDC_UPARROW;
		break;
	case MOUSE_CURSOR_WAIT:
		idc = IDC_WAIT;
		break;
	default:
		return;
	}

	HCURSOR hcursor = LoadCursor(NULL, idc);
	SetCursor(hcursor);
}

void Window::drag(int x, int y)
{
	PostMessage(hwnd, WM_NCLBUTTONDOWN, (WPARAM)HTCAPTION, MAKELPARAM(x, y));
}

void Window::show(bool show, bool activate)
{
	if (show && !IsWindowVisible(hwnd))
	{
		RECT client_rect;
		GetClientRect(hwnd, &client_rect);
		appendDirtyRect(client_rect);
		// Prepare the buffer before showing; WM_PAINT presents it after showing.
		flushPaint(NULL, false);
	}

	ShowWindow(hwnd, show ? (activate ? SW_SHOW : SW_SHOWNOACTIVATE) : SW_HIDE);
}

void Window::enable(bool enable)
{
	EnableWindow(hwnd, enable);
}

bool Window::destroy()
{
	Reference reference(this);
	// Finalizers released below must not reenter a live native wrapper.
	((Window_Object *)pyobj)->p = NULL;
	// Suppress callbacks until WM_DESTROY releases them, or a failed call can retry.
	destroying = true;
	if (!DestroyWindow(hwnd))
	{
		DWORD error = GetLastError();
		destroying = false;
		((Window_Object *)pyobj)->p = this;
		PyErr_SetFromWindowsErr(error);
		return false;
	}
	// The last native reference releases this object after WM_DESTROY.
	return true;
}

void Window::activate()
{
	SetActiveWindow(hwnd);
}

void Window::inactivate()
{
	HWND _hwnd = GetForegroundWindow();

	while (_hwnd)
	{
		LONG ex_style = GetWindowLong(_hwnd, GWL_EXSTYLE);

		TCHAR class_name[256] = {};
		GetClassName(_hwnd, class_name, _countof(class_name));

		if (wcscmp(class_name, WINDOW_CLASS_NAME.c_str()) != 0 && !(ex_style & WS_EX_TOPMOST) && IsWindowVisible(_hwnd) && IsWindowEnabled(_hwnd))
		{
			break;
		}

		_hwnd = GetWindow(_hwnd, GW_HWNDNEXT);
	}

	if (_hwnd)
	{
		HWND hwnd_last_active = GetLastActivePopup(_hwnd);
		SetForegroundWindow(hwnd_last_active);
	}
}

void Window::foreground()
{
	HWND hwnd_last_active = GetLastActivePopup(hwnd);
	SetForegroundWindow(hwnd_last_active);
}

void Window::restore()
{
	ShowWindow(hwnd, SW_RESTORE);
}

void Window::maximize()
{
	ShowWindow(hwnd, SW_MAXIMIZE);
}

void Window::minimize()
{
	ShowWindow(hwnd, SW_MINIMIZE);
}

void Window::topmost(bool topmost)
{
	if (topmost)
	{
		SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE);
	}
	else
	{
		SetWindowPos(hwnd, HWND_NOTOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE);
	}
}

bool Window::isEnabled()
{
	return ::IsWindowEnabled(hwnd) != FALSE;
}

bool Window::isVisible()
{
	return ::IsWindowVisible(hwnd) != FALSE;
}

bool Window::isMaximized()
{
	return ::IsZoomed(hwnd) != FALSE;
}

bool Window::isMinimized()
{
	return ::IsIconic(hwnd) != FALSE;
}

bool Window::isActive()
{
	return active;
}

bool Window::isForeground()
{
	return hwnd == GetForegroundWindow();
}

void Window::getWindowRect(RECT *rect)
{
	if (::IsIconic(hwnd))
	{
		*rect = last_valid_window_rect;
	}
	else
	{
		::GetWindowRect(hwnd, rect);
	}
}

void Window::getNormalWindowRect(RECT *rect)
{
	WINDOWPLACEMENT window_place;
	memset(&window_place, 0, sizeof(window_place));
	window_place.length = sizeof(window_place);
	::GetWindowPlacement(hwnd, &window_place);

	*rect = window_place.rcNormalPosition;
}

void Window::getNormalClientSize(SIZE *size)
{
	WINDOWPLACEMENT window_place;
	memset(&window_place, 0, sizeof(window_place));
	window_place.length = sizeof(window_place);
	::GetWindowPlacement(hwnd, &window_place);

	size->cx = window_place.rcNormalPosition.right - window_place.rcNormalPosition.left - window_frame_size.cx;
	size->cy = window_place.rcNormalPosition.bottom - window_place.rcNormalPosition.top - window_frame_size.cy;
}

float Window::getDisplayScaling()
{
	int dpi = GetDpiForWindow(hwnd);
	return ((float)dpi) / USER_DEFAULT_SCREEN_DPI;
}

struct _FindMonitorFromPositionContext
{
	_FindMonitorFromPositionContext()
		: x(0),
		  y(0),
		  monitor(0)
	{
	}

	int x;
	int y;
	HMONITOR monitor;
};

static BOOL CALLBACK _FindMonitorFromPosition(HMONITOR hMonitor, HDC hdcMonitor, LPRECT lprcMonitor, LPARAM dwData)
{
	_FindMonitorFromPositionContext *context = (_FindMonitorFromPositionContext *)dwData;

	MONITORINFO mi;
	mi.cbSize = sizeof(MONITORINFO);
	GetMonitorInfo(hMonitor, &mi);

	if (context->monitor == NULL && mi.dwFlags & MONITORINFOF_PRIMARY)
	{
		context->monitor = hMonitor;
	}

	if (context->x >= mi.rcMonitor.left &&
		context->y >= mi.rcMonitor.top &&
		context->x < mi.rcMonitor.right &&
		context->y < mi.rcMonitor.bottom)
	{
		context->monitor = hMonitor;
		return FALSE;
	}

	return TRUE;
}

int Window::getDpiFromPosition(int x, int y)
{
	_FindMonitorFromPositionContext context;
	context.x = x;
	context.y = y;

	EnumDisplayMonitors(NULL, NULL, _FindMonitorFromPosition, (LPARAM)&context);

	UINT dpi_x, dpi_y;
	GetDpiForMonitor(context.monitor, MDT_EFFECTIVE_DPI, &dpi_x, &dpi_y);

	return dpi_x;
}

float Window::getDisplayScalingFromPosition(int x, int y)
{
	return ((float)getDpiFromPosition(x, y)) / USER_DEFAULT_SCREEN_DPI;
}

void Window::clear()
{
	// Remove each owner before releasing Python references that can reenter clear.
	while (!plane_list.empty())
	{
		Plane *plane = plane_list.front();
		plane_list.pop_front();
		delete plane;
	}

	memset(&caret_rect, 0, sizeof(caret_rect));

	RECT dirty_rect = {};
	GetClientRect(hwnd, &dirty_rect);
	appendDirtyRect(dirty_rect);
}

void Window::setCaretRect(const RECT &rect)
{
	caret_blink = 2;

	appendDirtyRect(caret_rect);

	caret_rect = rect;

	appendDirtyRect(caret_rect);
}

void Window::setImeRect(const RECT &rect)
{
	ime_rect = rect;
}

void Window::enableIme(bool enable)
{
	if (enable)
	{
		if (ime_context)
		{
			ImmSetOpenStatus(ime_context, FALSE);
			ImmSetCompositionFontW(ime_context, &ime_logfont);
			ImmAssociateContext(hwnd, ime_context);
			ime_context = NULL;
		}
	}
	else
	{
		if (!ime_context)
		{
			ime_context = ImmAssociateContext(hwnd, NULL);
		}
	}
}

void Window::setImeFont(const LOGFONT &logfont)
{
	ime_logfont = logfont;

	// Apply the font immediately if an IME context is already available.
	HIMC imc = ImmGetContext(hwnd);
	if (imc)
	{
		ImmSetCompositionFontW(imc, &ime_logfont);
	}
	ImmReleaseContext(hwnd, imc);
}

// ----------------------------------------------------------------------------
//
// ----------------------------------------------------------------------------

TaskTrayIcon::Param::Param()
{
	lbuttondown_handler = NULL;
	lbuttonup_handler = NULL;
	rbuttondown_handler = NULL;
	rbuttonup_handler = NULL;
	lbuttondoubleclick_handler = NULL;
}

TaskTrayIcon::TaskTrayIcon(Param &param)
	: hwnd(NULL), native_ref_count(0), creating(true), popup_menu_active(false), pyobj(NULL), retry_timer(0)
{
	lbuttondown_handler = param.lbuttondown_handler;
	Py_XINCREF(lbuttondown_handler);
	lbuttonup_handler = param.lbuttonup_handler;
	Py_XINCREF(lbuttonup_handler);
	rbuttondown_handler = param.rbuttondown_handler;
	Py_XINCREF(rbuttondown_handler);
	rbuttonup_handler = param.rbuttonup_handler;
	Py_XINCREF(rbuttonup_handler);
	lbuttondoubleclick_handler = param.lbuttondoubleclick_handler;
	Py_XINCREF(lbuttondoubleclick_handler);

	HINSTANCE hInstance = GetModuleHandle(NULL);

	memset(&icon_data, 0, sizeof(icon_data));
	hwnd = CreateWindow(TASKTRAY_WINDOW_CLASS_NAME.c_str(), param.title.c_str(), WS_OVERLAPPEDWINDOW, CW_USEDEFAULT, 0, CW_USEDEFAULT, 0, NULL, NULL, hInstance, this);
	if (!hwnd)
	{
		if (!PyErr_Occurred())
			PyErr_SetFromWindowsErr(0);
		return;
	}

	icon_data.cbSize = sizeof(NOTIFYICONDATA);
	icon_data.uID = 0;
	icon_data.hWnd = hwnd;
	icon_data.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP;
	icon_data.hIcon = (HICON)LoadImage(hInstance, (const wchar_t *)1, IMAGE_ICON, 16, 16, 0);
	icon_data.uCallbackMessage = WM_USER_NTFYICON;
	lstrcpyn(icon_data.szTip, param.title.c_str(), _countof(icon_data.szTip));

	_addIconWithRetry();

	ShowWindow(hwnd, SW_HIDE);
	UpdateWindow(hwnd);
}

TaskTrayIcon::~TaskTrayIcon()
{
	// Invalidate before releasing callbacks, which may reenter Python methods.
	if (pyobj && ((TaskTrayIcon_Object *)pyobj)->p == this)
		((TaskTrayIcon_Object *)pyobj)->p = NULL;
	if (retry_timer)
		KillTimer(hwnd, retry_timer);
	if (hwnd)
		Shell_NotifyIcon(NIM_DELETE, &icon_data);
	if (icon_data.hIcon)
		DestroyIcon(icon_data.hIcon);
	_clearPopupMenuCommands();

	Py_CLEAR(lbuttondown_handler);
	Py_CLEAR(lbuttonup_handler);
	Py_CLEAR(rbuttondown_handler);
	Py_CLEAR(rbuttonup_handler);
	Py_CLEAR(lbuttondoubleclick_handler);
	Py_CLEAR(pyobj);
}

TaskTrayIcon::Reference::Reference(TaskTrayIcon *icon) : icon(icon)
{
	if (icon)
		++icon->native_ref_count;
}

TaskTrayIcon::Reference::~Reference()
{
	if (icon && --icon->native_ref_count == 0 && !icon->hwnd && !icon->creating)
		delete icon;
}

void TaskTrayIcon::SetPyObject(PyObject *_pyobj)
{
	if (pyobj != _pyobj)
	{
		Py_XDECREF(pyobj);
		pyobj = _pyobj;
		Py_XINCREF(pyobj);
	}
}

void TaskTrayIcon::destroy()
{
	DestroyWindow(hwnd);
}

bool TaskTrayIcon::_registerWindowClass()
{
	HINSTANCE hInstance = GetModuleHandle(NULL);

	WNDCLASSEX wc;
	memset(&wc, 0, sizeof(wc));
	wc.cbSize = sizeof(wc);
	wc.style = CS_HREDRAW | CS_VREDRAW;
	wc.lpfnWndProc = _wndProc;
	wc.cbClsExtra = 0;
	wc.cbWndExtra = 0;
	wc.hInstance = hInstance;
	wc.hIcon = 0;
	wc.hCursor = 0;
	wc.hbrBackground = CreateSolidBrush(RGB(0x00, 0x00, 0x00));
	wc.lpszMenuName = NULL;
	wc.lpszClassName = TASKTRAY_WINDOW_CLASS_NAME.c_str();
	wc.hIconSm = 0;

	if (!RegisterClassEx(&wc))
	{
		printf("RegisterClassEx failed\n");
		return (FALSE);
	}

	return (TRUE);
}

void TaskTrayIcon::_addIconWithRetry()
{
	if (retry_timer)
	{
		KillTimer(hwnd, retry_timer);
		retry_timer = 0;
	}
	// Shell_NotifyIcon does not always set last error on failure.
	SetLastError(ERROR_SUCCESS);
	if (Shell_NotifyIcon(NIM_ADD, &icon_data))
		return;

	DWORD err = GetLastError();
	printf("TaskTrayIcon : Shell_NotifyIcon(NIM_ADD) failed : %lu\n", err);
	if (err == ERROR_TIMEOUT || err == ERROR_SUCCESS)
	{
		// Keep retrying after Explorer recovers without blocking the UI thread.
		retry_timer = SetTimer(hwnd, TIMER_TASKTRAY_RETRY, 1000, NULL);
		if (!retry_timer)
			printf("TaskTrayIcon : SetTimer failed : %lu\n", GetLastError());
	}
}

void TaskTrayIcon::_clearPopupMenuCommands()
{
	std::vector<PyObject *> commands;
	commands.swap(popup_menu_commands);
	for (size_t i = 0; i < commands.size(); ++i)
		Py_XDECREF(commands[i]);
}

LRESULT CALLBACK TaskTrayIcon::_wndProc(HWND hwnd, UINT msg, WPARAM wp, LPARAM lp)
{
	TaskTrayIcon *task_tray_icon = (TaskTrayIcon *)GetProp(hwnd, L"ckit_userdata");

	PythonUtil::GIL_Ensure gil_ensure;
	if (!task_tray_icon && msg != WM_CREATE)
		return DefWindowProc(hwnd, msg, wp, lp);
	Reference reference(task_tray_icon);

	switch (msg)
	{
	case WM_CREATE:
	{
		CREATESTRUCT *create_data = (CREATESTRUCT *)lp;
		TaskTrayIcon *task_tray_icon = (TaskTrayIcon *)create_data->lpCreateParams;
		task_tray_icon->hwnd = hwnd;
		if (!SetProp(hwnd, L"ckit_userdata", task_tray_icon))
		{
			PyErr_SetFromWindowsErr(0);
			return -1;
		}
	}
	break;

	case WM_DESTROY:
	{
		RemoveProp(hwnd, L"ckit_userdata");
		if (task_tray_icon->pyobj && ((TaskTrayIcon_Object *)task_tray_icon->pyobj)->p == task_tray_icon)
			((TaskTrayIcon_Object *)task_tray_icon->pyobj)->p = NULL;
		if (task_tray_icon->retry_timer)
		{
			KillTimer(hwnd, task_tray_icon->retry_timer);
			task_tray_icon->retry_timer = 0;
		}
		Shell_NotifyIcon(NIM_DELETE, &task_tray_icon->icon_data);
		task_tray_icon->hwnd = NULL;
	}
	break;

	case WM_COMMAND:
	{
		int wmId = LOWORD(wp);
		int wmEvent = HIWORD(wp);

		if (ID_POPUP_MENUITEM <= wmId && wmId < ID_POPUP_MENUITEM + (int)task_tray_icon->popup_menu_commands.size())
		{
			PyObject *func = task_tray_icon->popup_menu_commands[wmId - ID_POPUP_MENUITEM];
			if (func)
			{
				Py_INCREF(func);
				PyObject *command_info;
				if (command_info_constructor)
				{
					PyObject *pyarglist2 = Py_BuildValue("()");
					command_info = PyObject_Call(command_info_constructor, pyarglist2, NULL);
					Py_DECREF(pyarglist2);
					if (!command_info)
					{
						PyErr_Print();
						Py_DECREF(func);
						break;
					}
				}
				else
				{
					command_info = Py_None;
					Py_INCREF(command_info);
				}

				if (!task_tray_icon->hwnd)
				{
					Py_DECREF(command_info);
					Py_DECREF(func);
					break;
				}
				PyObject *pyarglist = Py_BuildValue("(O)", command_info);
				Py_DECREF(command_info);
				PyObject *pyresult = PyObject_Call(func, pyarglist, NULL);
				Py_DECREF(func);
				Py_DECREF(pyarglist);
				if (pyresult)
				{
					Py_DECREF(pyresult);
				}
				else
				{
					PyErr_Print();
				}
			}
		}
		else
		{
			return DefWindowProc(hwnd, msg, wp, lp);
		}
	}
	break;

	case WM_USER_NTFYICON:
	{
		switch (lp)
		{
		case WM_LBUTTONDOWN:
			if (task_tray_icon->lbuttondown_handler)
			{
				int mod = Window::_getModKey();

				PyObject *pyarglist = Py_BuildValue("(iii)", (short)LOWORD(lp), (short)HIWORD(lp), mod);
				PyObject *pyresult = PyObject_Call(task_tray_icon->lbuttondown_handler, pyarglist, NULL);
				Py_DECREF(pyarglist);
				if (pyresult)
				{
					Py_DECREF(pyresult);
				}
				else
				{
					PyErr_Print();
				}
			}
			break;

		case WM_LBUTTONUP:
			if (task_tray_icon->lbuttonup_handler)
			{
				int mod = Window::_getModKey();

				PyObject *pyarglist = Py_BuildValue("(iii)", (short)LOWORD(lp), (short)HIWORD(lp), mod);
				PyObject *pyresult = PyObject_Call(task_tray_icon->lbuttonup_handler, pyarglist, NULL);
				Py_DECREF(pyarglist);
				if (pyresult)
				{
					Py_DECREF(pyresult);
				}
				else
				{
					PyErr_Print();
				}
			}
			break;

		case WM_RBUTTONDOWN:
			if (task_tray_icon->rbuttondown_handler)
			{
				int mod = Window::_getModKey();

				PyObject *pyarglist = Py_BuildValue("(iii)", (short)LOWORD(lp), (short)HIWORD(lp), mod);
				PyObject *pyresult = PyObject_Call(task_tray_icon->rbuttondown_handler, pyarglist, NULL);
				Py_DECREF(pyarglist);
				if (pyresult)
				{
					Py_DECREF(pyresult);
				}
				else
				{
					PyErr_Print();
				}
			}
			break;

		case WM_RBUTTONUP:
			if (task_tray_icon->rbuttonup_handler)
			{
				int mod = Window::_getModKey();

				PyObject *pyarglist = Py_BuildValue("(iii)", (short)LOWORD(lp), (short)HIWORD(lp), mod);
				PyObject *pyresult = PyObject_Call(task_tray_icon->rbuttonup_handler, pyarglist, NULL);
				Py_DECREF(pyarglist);
				if (pyresult)
				{
					Py_DECREF(pyresult);
				}
				else
				{
					PyErr_Print();
				}
			}
			break;

		case WM_LBUTTONDBLCLK:
			if (task_tray_icon->lbuttondoubleclick_handler)
			{
				int mod = Window::_getModKey();

				PyObject *pyarglist = Py_BuildValue("(iii)", (short)LOWORD(lp), (short)HIWORD(lp), mod);
				PyObject *pyresult = PyObject_Call(task_tray_icon->lbuttondoubleclick_handler, pyarglist, NULL);
				Py_DECREF(pyarglist);
				if (pyresult)
				{
					Py_DECREF(pyresult);
				}
				else
				{
					PyErr_Print();
				}
			}
			break;
		}
	}
	break;

	case WM_TIMER:
		if (task_tray_icon->retry_timer && wp == task_tray_icon->retry_timer)
		{
			KillTimer(hwnd, task_tray_icon->retry_timer);
			task_tray_icon->retry_timer = 0;
			// A timed-out ADD may already have registered the icon.
			if (!Shell_NotifyIcon(NIM_MODIFY, &task_tray_icon->icon_data))
				task_tray_icon->_addIconWithRetry();
		}
		return 0;

	case WM_PAINT:
	{
		PAINTSTRUCT ps;
		HDC hdc = BeginPaint(hwnd, &ps);
		EndPaint(hwnd, &ps);
	}
	break;

	default:
		if (msg == WM_TASKBAR_CREATED)
		{
			Shell_NotifyIcon(NIM_DELETE, &task_tray_icon->icon_data);
			task_tray_icon->_addIconWithRetry();
		}
		return DefWindowProc(hwnd, msg, wp, lp);
	}
	return 0;
}

// ----------------------------------------------------------------------------
//
// ----------------------------------------------------------------------------

static int Attribute_init(PyObject *self, PyObject *args, PyObject *kwds)
{
	PyObject *fg = NULL;
	PyObject *bg = NULL;
	PyObject *bg_gradation = NULL;
	PyObject *line0 = NULL;
	PyObject *line1 = NULL;

	static char *kwlist[] = {
		"fg",
		"bg",
		"bg_gradation",
		"line0",
		"line1",
		NULL};

	if (!PyArg_ParseTupleAndKeywords(args, kwds, "|OOOOO", kwlist,
									 &fg,
									 &bg,
									 &bg_gradation,
									 &line0,
									 &line1))
	{
		return -1;
	}

	if (fg && PySequence_Check(fg))
	{
		int r, g, b;
		if (!PyArg_ParseTuple(fg, "iii", &r, &g, &b))
			return -1;

		((Attribute_Object *)self)->attr.fg_color = RGB(r, g, b);
	}

	if (bg_gradation && PySequence_Check(bg_gradation))
	{
		int r[4], g[4], b[4];

		if (!PyArg_ParseTuple(
				bg_gradation,
				"(iii)(iii)(iii)(iii)",
				&r[0], &g[0], &b[0],
				&r[1], &g[1], &b[1],
				&r[2], &g[2], &b[2],
				&r[3], &g[3], &b[3]))
		{
			return -1;
		}

		((Attribute_Object *)self)->attr.bg = Attribute::BG_Gradation;
		((Attribute_Object *)self)->attr.bg_color[0] = RGB(r[0], g[0], b[0]);
		((Attribute_Object *)self)->attr.bg_color[1] = RGB(r[1], g[1], b[1]);
		((Attribute_Object *)self)->attr.bg_color[2] = RGB(r[2], g[2], b[2]);
		((Attribute_Object *)self)->attr.bg_color[3] = RGB(r[3], g[3], b[3]);
	}
	else if (bg && PySequence_Check(bg))
	{
		int r, g, b;
		if (!PyArg_ParseTuple(bg, "iii", &r, &g, &b))
			return -1;

		((Attribute_Object *)self)->attr.bg = Attribute::BG_Flat;
		((Attribute_Object *)self)->attr.bg_color[0] = RGB(r, g, b);
	}

	if (line0 && PySequence_Check(line0))
	{
		int line;
		int r, g, b;
		if (!PyArg_ParseTuple(line0, "i(iii)", &line, &r, &g, &b))
			return -1;

		((Attribute_Object *)self)->attr.line[0] = line;
		((Attribute_Object *)self)->attr.line_color[0] = RGB(r, g, b);
	}

	if (line1 && PySequence_Check(line1))
	{
		int line;
		int r, g, b;
		if (!PyArg_ParseTuple(line1, "i(iii)", &line, &r, &g, &b))
			return -1;

		((Attribute_Object *)self)->attr.line[1] = line;
		((Attribute_Object *)self)->attr.line_color[1] = RGB(r, g, b);
	}

	return 0;
}

static void Attribute_dealloc(PyObject *self)
{
	self->ob_type->tp_free(self);
}

static PyMethodDef Attribute_methods[] = {
	{NULL, NULL}};

PyTypeObject Attribute_Type = {
	PyVarObject_HEAD_INIT(NULL, 0) "Attribute", /* tp_name */
	sizeof(Attribute_Object),					/* tp_basicsize */
	0,											/* tp_itemsize */
	(destructor)Attribute_dealloc,				/* tp_dealloc */
	0,											/* tp_print */
	0,											/* tp_getattr */
	0,											/* tp_setattr */
	0,											/* tp_reserved */
	0,											/* tp_repr */
	0,											/* tp_as_number */
	0,											/* tp_as_sequence */
	0,											/* tp_as_mapping */
	0,											/* tp_hash */
	0,											/* tp_call */
	0,											/* tp_str */
	PyObject_GenericGetAttr,					/* tp_getattro */
	PyObject_GenericSetAttr,					/* tp_setattro */
	0,											/* tp_as_buffer */
	Py_TPFLAGS_DEFAULT | Py_TPFLAGS_BASETYPE,	/* tp_flags */
	"",											/* tp_doc */
	0,											/* tp_traverse */
	0,											/* tp_clear */
	0,											/* tp_richcompare */
	0,											/* tp_weaklistoffset */
	0,											/* tp_iter */
	0,											/* tp_iternext */
	Attribute_methods,							/* tp_methods */
	0,											/* tp_members */
	0,											/* tp_getset */
	0,											/* tp_base */
	0,											/* tp_dict */
	0,											/* tp_descr_get */
	0,											/* tp_descr_set */
	0,											/* tp_dictoffset */
	Attribute_init,								/* tp_init */
	0,											/* tp_alloc */
	PyType_GenericNew,							/* tp_new */
	0,											/* tp_free */
};

// ----------------------------------------------------------------------------
//
// ----------------------------------------------------------------------------

static PyObject *Image_new(PyTypeObject *type, PyObject *args, PyObject *kwds)
{
	PyErr_SetString(PyExc_TypeError, "Image cannot be instantiated directly; use Image.fromBytes().");
	return NULL;
}

static void Image_dealloc(PyObject *self)
{
	Image *image = ((Image_Object *)self)->p;
	image->Release();
	self->ob_type->tp_free(self);
}

static PyObject *Image_getSize(PyObject *self, PyObject *args)
{
	if (!PyArg_ParseTuple(args, ""))
		return NULL;
	return Py_BuildValue("(ii)", ((Image_Object *)self)->p->width, ((Image_Object *)self)->p->height);
}

static void _Image_ConvertRGBAtoDIB(char *dst, const char *src, size_t w, size_t h, size_t wb)
{
	for (size_t y = 0; y < h; y++)
	{
		for (size_t x = 0; x < w; x++)
		{
			size_t src_y = h - y - 1;
			dst[y * w * 4 + x * 4 + 0] = src[src_y * wb + x * 4 + 2];
			dst[y * w * 4 + x * 4 + 1] = src[src_y * wb + x * 4 + 1];
			dst[y * w * 4 + x * 4 + 2] = src[src_y * wb + x * 4 + 0];
			dst[y * w * 4 + x * 4 + 3] = src[src_y * wb + x * 4 + 3];
		}
	}
}

static PyObject *Image_fromBytes(PyObject *self, PyObject *args)
{
	int width;
	int height;
	const char *buf;
	Py_ssize_t bufsize;
	PyObject *py_transparent_color = NULL;
	int halftone = 0;

	if (!PyArg_ParseTuple(args, "(ii)y#|Oi", &width, &height, &buf, &bufsize, &py_transparent_color, &halftone))
		return NULL;

	if (py_transparent_color == Py_None)
	{
		py_transparent_color = NULL;
	}

	size_t byte_count = 0;
	if (width > 0 && height > 0)
	{
		if ((size_t)width > (size_t)PY_SSIZE_T_MAX / 4 / (size_t)height)
		{
			PyErr_SetString(PyExc_OverflowError, "image byte count exceeds Py_ssize_t range.");
			return NULL;
		}
		byte_count = (size_t)width * 4 * (size_t)height;
	}
	if (byte_count > (size_t)bufsize)
	{
		PyErr_SetString(PyExc_ValueError, "insufficient buffer length.");
		return NULL;
	}

	COLORREF transparent_color = RGB(0, 0, 0);
	if (py_transparent_color)
	{
		int r, g, b;
		if (!PyArg_ParseTuple(py_transparent_color, "iii", &r, &g, &b))
			return NULL;

		transparent_color = RGB(r, g, b);
	}

	void *dib_buf = NULL;
	if (byte_count)
	{
		dib_buf = malloc(byte_count);
		if (!dib_buf)
			return PyErr_NoMemory();
		_Image_ConvertRGBAtoDIB((char *)dib_buf, buf, width, height, (size_t)width * 4);
	}

	Image *image = byte_count
		? new (std::nothrow) Image(width, height, (const char *)dib_buf, py_transparent_color ? &transparent_color : 0, halftone != 0)
		: new (std::nothrow) Image(0, 0, NULL, false);
	free(dib_buf);
	if (!image)
		return PyErr_NoMemory();
	if (!image->handle)
	{
		delete image;
		return NULL;
	}

	Image_Object *pyimg = PyObject_New(Image_Object, &Image_Type);
	if (!pyimg)
	{
		delete image;
		return NULL;
	}
	pyimg->p = image;
	image->AddRef();

	return (PyObject *)pyimg;
}

static PyMethodDef Image_methods[] = {
	{"getSize", Image_getSize, METH_VARARGS, ""},
	{"fromBytes", Image_fromBytes, METH_STATIC | METH_VARARGS, ""},
	{NULL, NULL}};

PyTypeObject Image_Type = {
	PyVarObject_HEAD_INIT(NULL, 0) "Image",	  /* tp_name */
	sizeof(Image_Object),					  /* tp_basicsize */
	0,										  /* tp_itemsize */
	Image_dealloc,							  /* tp_dealloc */
	0,										  /* tp_print */
	0,										  /* tp_getattr */
	0,										  /* tp_setattr */
	0,										  /* tp_reserved */
	0,										  /* tp_repr */
	0,										  /* tp_as_number */
	0,										  /* tp_as_sequence */
	0,										  /* tp_as_mapping */
	0,										  /* tp_hash */
	0,										  /* tp_call */
	0,										  /* tp_str */
	PyObject_GenericGetAttr,				  /* tp_getattro */
	PyObject_GenericSetAttr,				  /* tp_setattro */
	0,										  /* tp_as_buffer */
	Py_TPFLAGS_DEFAULT | Py_TPFLAGS_BASETYPE, /* tp_flags */
	"",										  /* tp_doc */
	0,										  /* tp_traverse */
	0,										  /* tp_clear */
	0,										  /* tp_richcompare */
	0,										  /* tp_weaklistoffset */
	0,										  /* tp_iter */
	0,										  /* tp_iternext */
	Image_methods,							  /* tp_methods */
	0,										  /* tp_members */
	0,										  /* tp_getset */
	0,										  /* tp_base */
	0,										  /* tp_dict */
	0,										  /* tp_descr_get */
	0,										  /* tp_descr_set */
	0,										  /* tp_dictoffset */
	0,										  /* tp_init */
	0,										  /* tp_alloc */
	Image_new,						  /* tp_new */
	0,										  /* tp_free */
};

// ----------------------------------------------------------------------------
//
// ----------------------------------------------------------------------------

static int Font_init(PyObject *self, PyObject *args, PyObject *kwds)
{
	PyObject *pystr_name;
	int size;
	int padding = 0;

	if (!PyArg_ParseTuple(args, "Oi|i", &pystr_name, &size, &padding))
	{
		return -1;
	}

	if (!PyUnicode_Check(pystr_name))
	{
		PyErr_SetString(PyExc_TypeError, "must be unicode.");
		return -1;
	}
	// A NULL length makes the Unicode API reject embedded NULs.
	wchar_t *name = PyUnicode_AsWideCharString(pystr_name, NULL);
	if (!name)
		return -1;

	Font *font;
	try
	{
		font = new Font(name, size, padding);
	}
	catch (const std::bad_alloc &)
	{
		PyMem_Free(name);
		PyErr_NoMemory();
		return -1;
	}
	PyMem_Free(name);
	if (!font->handle)
	{
		delete font;
		return -1;
	}

	Font *oldfont = ((Font_Object *)self)->p;
	((Font_Object *)self)->p = font;
	font->AddRef();
	if (oldfont)
		oldfont->Release();

	return 0;
}

static void Font_dealloc(PyObject *self)
{
	Font *font = ((Font_Object *)self)->p;
	if (font)
		font->Release();
	self->ob_type->tp_free(self);
}

static PyObject *Font_getCharSize(PyObject *self, PyObject *args)
{
	if (!PyArg_ParseTuple(args, ""))
		return NULL;

	if (!((Font_Object *)self)->p)
	{
		PyErr_SetString(PyExc_ValueError, "already destroyed.");
		return NULL;
	}

	Font *font = ((Font_Object *)self)->p;

	PyObject *pyret = Py_BuildValue("(ii)", font->char_width, font->char_height);
	return pyret;
}

static PyMethodDef Font_methods[] = {
	{"getCharSize", Font_getCharSize, METH_VARARGS, ""},
	{NULL, NULL}};

PyTypeObject Font_Type = {
	PyVarObject_HEAD_INIT(NULL, 0) "Font",	  /* tp_name */
	sizeof(Font_Object),					  /* tp_basicsize */
	0,										  /* tp_itemsize */
	(destructor)Font_dealloc,				  /* tp_dealloc */
	0,										  /* tp_print */
	0,										  /* tp_getattr */
	0,										  /* tp_setattr */
	0,										  /* tp_reserved */
	0,										  /* tp_repr */
	0,										  /* tp_as_number */
	0,										  /* tp_as_sequence */
	0,										  /* tp_as_mapping */
	0,										  /* tp_hash */
	0,										  /* tp_call */
	0,										  /* tp_str */
	PyObject_GenericGetAttr,				  /* tp_getattro */
	PyObject_GenericSetAttr,				  /* tp_setattro */
	0,										  /* tp_as_buffer */
	Py_TPFLAGS_DEFAULT | Py_TPFLAGS_BASETYPE, /* tp_flags */
	"",										  /* tp_doc */
	0,										  /* tp_traverse */
	0,										  /* tp_clear */
	0,										  /* tp_richcompare */
	0,										  /* tp_weaklistoffset */
	0,										  /* tp_iter */
	0,										  /* tp_iternext */
	Font_methods,							  /* tp_methods */
	0,										  /* tp_members */
	0,										  /* tp_getset */
	0,										  /* tp_base */
	0,										  /* tp_dict */
	0,										  /* tp_descr_get */
	0,										  /* tp_descr_set */
	0,										  /* tp_dictoffset */
	Font_init,								  /* tp_init */
	0,										  /* tp_alloc */
	PyType_GenericNew,						  /* tp_new */
	0,										  /* tp_free */
};

// ----------------------------------------------------------------------------
//
// ----------------------------------------------------------------------------

static int ImagePlane_init(PyObject *self, PyObject *args, PyObject *kwds)
{
	PyObject *window;
	int x, y, width, height;
	float priority;

	if (!PyArg_ParseTuple(args, "O(ii)(ii)f",
						  &window,
						  &x,
						  &y,
						  &width,
						  &height,
						  &priority))
	{
		return -1;
	}

	if (!Window_Check(window))
	{
		PyErr_SetString(PyExc_TypeError, "must be a Window object.");
		return -1;
	}
	if (!((Window_Object *)window)->p)
	{
		PyErr_SetString(PyExc_ValueError, "window is already destroyed or uninitialized.");
		return -1;
	}

	ImagePlane *plane = new ImagePlane(((Window_Object *)window)->p, x, y, width, height, priority);

	plane->SetPyObject(self);

	((ImagePlane_Object *)self)->p = plane;

	std::list<Plane *>::iterator i;
	std::list<Plane *> &plane_list = ((Window_Object *)window)->p->plane_list;
	for (i = plane_list.begin(); i != plane_list.end(); i++)
	{
		if ((*i)->priority <= priority)
		{
			break;
		}
	}
	plane_list.insert(i, plane);

	return 0;
}

static void ImagePlane_dealloc(PyObject *self)
{
	ImagePlane *plane = ((ImagePlane_Object *)self)->p;
	if (plane)
	{
		plane->SetPyObject(NULL);
	}
	self->ob_type->tp_free(self);
}

static PyObject *ImagePlane_destroy(PyObject *self, PyObject *args)
{
	if (!PyArg_ParseTuple(args, ""))
		return NULL;

	if (!((ImagePlane_Object *)self)->p)
	{
		PyErr_SetString(PyExc_ValueError, "already destroyed.");
		return NULL;
	}

	((ImagePlane_Object *)self)->p->window->plane_list.remove(((ImagePlane_Object *)self)->p);

	delete ((ImagePlane_Object *)self)->p;

	Py_INCREF(Py_None);
	return Py_None;
}

static PyObject *ImagePlane_show(PyObject *self, PyObject *args)
{
	int show;
	if (!PyArg_ParseTuple(args, "i", &show))
		return NULL;

	if (!((ImagePlane_Object *)self)->p)
	{
		PyErr_SetString(PyExc_ValueError, "already destroyed.");
		return NULL;
	}

	((ImagePlane_Object *)self)->p->Show(show != 0);

	Py_INCREF(Py_None);
	return Py_None;
}

static PyObject *ImagePlane_getPosition(PyObject *self, PyObject *args)
{
	if (!PyArg_ParseTuple(args, ""))
		return NULL;

	if (!((ImagePlane_Object *)self)->p)
	{
		PyErr_SetString(PyExc_ValueError, "already destroyed.");
		return NULL;
	}

	return Py_BuildValue("(ii)", ((ImagePlane_Object *)self)->p->x, ((ImagePlane_Object *)self)->p->y);
}

static PyObject *ImagePlane_setPosition(PyObject *self, PyObject *args)
{
	int x, y;
	if (!PyArg_ParseTuple(args, "(ii)", &x, &y))
		return NULL;

	if (!((ImagePlane_Object *)self)->p)
	{
		PyErr_SetString(PyExc_ValueError, "already destroyed.");
		return NULL;
	}

	((ImagePlane_Object *)self)->p->SetPosition(x, y);

	Py_INCREF(Py_None);
	return Py_None;
}

static PyObject *ImagePlane_getSize(PyObject *self, PyObject *args)
{
	if (!PyArg_ParseTuple(args, ""))
		return NULL;

	if (!((ImagePlane_Object *)self)->p)
	{
		PyErr_SetString(PyExc_ValueError, "already destroyed.");
		return NULL;
	}

	return Py_BuildValue("(ii)", ((ImagePlane_Object *)self)->p->width, ((ImagePlane_Object *)self)->p->height);
}

static PyObject *ImagePlane_setSize(PyObject *self, PyObject *args)
{
	int width, height;
	if (!PyArg_ParseTuple(args, "(ii)", &width, &height))
		return NULL;

	if (!((ImagePlane_Object *)self)->p)
	{
		PyErr_SetString(PyExc_ValueError, "already destroyed.");
		return NULL;
	}

	((ImagePlane_Object *)self)->p->SetSize(width, height);

	Py_INCREF(Py_None);
	return Py_None;
}

static PyObject *ImagePlane_getPriority(PyObject *self, PyObject *args)
{
	if (!PyArg_ParseTuple(args, ""))
		return NULL;

	if (!((ImagePlane_Object *)self)->p)
	{
		PyErr_SetString(PyExc_ValueError, "already destroyed.");
		return NULL;
	}

	return Py_BuildValue("f", ((ImagePlane_Object *)self)->p->priority);
}

static PyObject *ImagePlane_setPriority(PyObject *self, PyObject *args)
{
	float priority;
	if (!PyArg_ParseTuple(args, "f", &priority))
		return NULL;

	if (!((ImagePlane_Object *)self)->p)
	{
		PyErr_SetString(PyExc_ValueError, "already destroyed.");
		return NULL;
	}

	((ImagePlane_Object *)self)->p->SetPriority(priority);

	Py_INCREF(Py_None);
	return Py_None;
}

static PyObject *ImagePlane_getImage(PyObject *self, PyObject *args)
{
	if (!PyArg_ParseTuple(args, ""))
		return NULL;

	if (!((ImagePlane_Object *)self)->p)
	{
		PyErr_SetString(PyExc_ValueError, "already destroyed.");
		return NULL;
	}

	Image *image = ((ImagePlane_Object *)self)->p->image;
	if (image)
	{
		Image_Object *pyimg;
		pyimg = PyObject_New(Image_Object, &Image_Type);
		pyimg->p = image;
		image->AddRef();
		return (PyObject *)pyimg;
	}
	else
	{
		Py_INCREF(Py_None);
		return Py_None;
	}
}

static PyObject *ImagePlane_setImage(PyObject *self, PyObject *args)
{
	PyObject *image;
	if (!PyArg_ParseTuple(args, "O", &image))
		return NULL;

	if (!((ImagePlane_Object *)self)->p)
	{
		PyErr_SetString(PyExc_ValueError, "already destroyed.");
		return NULL;
	}

	if (!Image_Check(image))
	{
		PyErr_SetString(PyExc_TypeError, "must be a Image object.");
		return NULL;
	}

	((ImagePlane_Object *)self)->p->SetImage(((Image_Object *)image)->p);

	Py_INCREF(Py_None);
	return Py_None;
}

static PyMethodDef ImagePlane_methods[] = {

	{"destroy", ImagePlane_destroy, METH_VARARGS, ""},

	{"show", ImagePlane_show, METH_VARARGS, ""},

	{"getPosition", ImagePlane_getPosition, METH_VARARGS, ""},
	{"getSize", ImagePlane_getSize, METH_VARARGS, ""},
	{"getPriority", ImagePlane_getPriority, METH_VARARGS, ""},
	{"getImage", ImagePlane_getImage, METH_VARARGS, ""},

	{"setPosition", ImagePlane_setPosition, METH_VARARGS, ""},
	{"setSize", ImagePlane_setSize, METH_VARARGS, ""},
	{"setPriority", ImagePlane_setPriority, METH_VARARGS, ""},
	{"setImage", ImagePlane_setImage, METH_VARARGS, ""},

	{NULL, NULL}};

PyTypeObject ImagePlane_Type = {
	PyVarObject_HEAD_INIT(NULL, 0) "ImagePlane", /* tp_name */
	sizeof(ImagePlane_Object),					 /* tp_basicsize */
	0,											 /* tp_itemsize */
	ImagePlane_dealloc,							 /* tp_dealloc */
	0,											 /* tp_print */
	0,											 /* tp_getattr */
	0,											 /* tp_setattr */
	0,											 /* tp_reserved */
	0,											 /* tp_repr */
	0,											 /* tp_as_number */
	0,											 /* tp_as_sequence */
	0,											 /* tp_as_mapping */
	0,											 /* tp_hash */
	0,											 /* tp_call */
	0,											 /* tp_str */
	PyObject_GenericGetAttr,					 /* tp_getattro */
	PyObject_GenericSetAttr,					 /* tp_setattro */
	0,											 /* tp_as_buffer */
	Py_TPFLAGS_DEFAULT | Py_TPFLAGS_BASETYPE,	 /* tp_flags */
	"",											 /* tp_doc */
	0,											 /* tp_traverse */
	0,											 /* tp_clear */
	0,											 /* tp_richcompare */
	0,											 /* tp_weaklistoffset */
	0,											 /* tp_iter */
	0,											 /* tp_iternext */
	ImagePlane_methods,							 /* tp_methods */
	0,											 /* tp_members */
	0,											 /* tp_getset */
	0,											 /* tp_base */
	0,											 /* tp_dict */
	0,											 /* tp_descr_get */
	0,											 /* tp_descr_set */
	0,											 /* tp_dictoffset */
	ImagePlane_init,							 /* tp_init */
	0,											 /* tp_alloc */
	PyType_GenericNew,							 /* tp_new */
	0,											 /* tp_free */
};

// ----------------------------------------------------------------------------
//
// ----------------------------------------------------------------------------

static int TextPlane_init(PyObject *self, PyObject *args, PyObject *kwds)
{
	PyObject *window;
	int x, y, width, height;
	float priority;

	if (!PyArg_ParseTuple(args, "O(ii)(ii)f",
						  &window,
						  &x,
						  &y,
						  &width,
						  &height,
						  &priority))
	{
		return -1;
	}

	if (!Window_Check(window))
	{
		PyErr_SetString(PyExc_TypeError, "must be a Window object.");
		return -1;
	}
	if (!((Window_Object *)window)->p)
	{
		PyErr_SetString(PyExc_ValueError, "window is already destroyed or uninitialized.");
		return -1;
	}

	TextPlane *plane = new TextPlane(((Window_Object *)window)->p, x, y, width, height, priority);

	plane->SetPyObject(self);

	((TextPlane_Object *)self)->p = plane;

	std::list<Plane *>::iterator i;
	std::list<Plane *> &plane_list = ((Window_Object *)window)->p->plane_list;
	for (i = plane_list.begin(); i != plane_list.end(); i++)
	{
		if ((*i)->priority <= priority)
		{
			break;
		}
	}
	plane_list.insert(i, plane);

	return 0;
}

static void TextPlane_dealloc(PyObject *self)
{
	TextPlane *plane = ((TextPlane_Object *)self)->p;
	if (plane)
	{
		plane->SetPyObject(NULL);
	}
	self->ob_type->tp_free(self);
}

static PyObject *TextPlane_destroy(PyObject *self, PyObject *args)
{
	if (!PyArg_ParseTuple(args, ""))
		return NULL;

	if (!((TextPlane_Object *)self)->p)
	{
		PyErr_SetString(PyExc_ValueError, "already destroyed.");
		return NULL;
	}

	((TextPlane_Object *)self)->p->window->plane_list.remove(((TextPlane_Object *)self)->p);

	delete ((TextPlane_Object *)self)->p;

	Py_INCREF(Py_None);
	return Py_None;
}

static PyObject *TextPlane_show(PyObject *self, PyObject *args)
{
	int show;
	if (!PyArg_ParseTuple(args, "i", &show))
		return NULL;

	if (!((TextPlane_Object *)self)->p)
	{
		PyErr_SetString(PyExc_ValueError, "already destroyed.");
		return NULL;
	}

	((TextPlane_Object *)self)->p->Show(show != 0);

	Py_INCREF(Py_None);
	return Py_None;
}

static PyObject *TextPlane_getPosition(PyObject *self, PyObject *args)
{
	if (!PyArg_ParseTuple(args, ""))
		return NULL;

	if (!((TextPlane_Object *)self)->p)
	{
		PyErr_SetString(PyExc_ValueError, "already destroyed.");
		return NULL;
	}

	return Py_BuildValue("(ii)", ((TextPlane_Object *)self)->p->x, ((TextPlane_Object *)self)->p->y);
}

static PyObject *TextPlane_setPosition(PyObject *self, PyObject *args)
{
	int x, y;
	if (!PyArg_ParseTuple(args, "(ii)", &x, &y))
		return NULL;

	if (!((TextPlane_Object *)self)->p)
	{
		PyErr_SetString(PyExc_ValueError, "already destroyed.");
		return NULL;
	}

	((TextPlane_Object *)self)->p->SetPosition(x, y);

	Py_INCREF(Py_None);
	return Py_None;
}

static PyObject *TextPlane_getSize(PyObject *self, PyObject *args)
{
	if (!PyArg_ParseTuple(args, ""))
		return NULL;

	if (!((TextPlane_Object *)self)->p)
	{
		PyErr_SetString(PyExc_ValueError, "already destroyed.");
		return NULL;
	}

	return Py_BuildValue("(ii)", ((TextPlane_Object *)self)->p->width, ((TextPlane_Object *)self)->p->height);
}

static PyObject *TextPlane_setSize(PyObject *self, PyObject *args)
{
	int width, height;
	if (!PyArg_ParseTuple(args, "(ii)", &width, &height))
		return NULL;

	if (!((TextPlane_Object *)self)->p)
	{
		PyErr_SetString(PyExc_ValueError, "already destroyed.");
		return NULL;
	}

	((TextPlane_Object *)self)->p->SetSize(width, height);

	Py_INCREF(Py_None);
	return Py_None;
}

static PyObject *TextPlane_getPriority(PyObject *self, PyObject *args)
{
	if (!PyArg_ParseTuple(args, ""))
		return NULL;

	if (!((TextPlane_Object *)self)->p)
	{
		PyErr_SetString(PyExc_ValueError, "already destroyed.");
		return NULL;
	}

	return Py_BuildValue("f", ((TextPlane_Object *)self)->p->priority);
}

static PyObject *TextPlane_setPriority(PyObject *self, PyObject *args)
{
	float priority;
	if (!PyArg_ParseTuple(args, "f", &priority))
		return NULL;

	if (!((TextPlane_Object *)self)->p)
	{
		PyErr_SetString(PyExc_ValueError, "already destroyed.");
		return NULL;
	}

	((TextPlane_Object *)self)->p->SetPriority(priority);

	Py_INCREF(Py_None);
	return Py_None;
}

static PyObject *TextPlane_getFont(PyObject *self, PyObject *args)
{
	if (!PyArg_ParseTuple(args, ""))
		return NULL;

	if (!((TextPlane_Object *)self)->p)
	{
		PyErr_SetString(PyExc_ValueError, "already destroyed.");
		return NULL;
	}

	Font *font = ((TextPlane_Object *)self)->p->font;
	if (font)
	{
		Font_Object *pyfont;
		pyfont = PyObject_New(Font_Object, &Font_Type);
		pyfont->p = font;
		font->AddRef();
		return (PyObject *)pyfont;
	}
	else
	{
		Py_INCREF(Py_None);
		return Py_None;
	}
}

static PyObject *TextPlane_setFont(PyObject *self, PyObject *args)
{
	PyObject *font;
	if (!PyArg_ParseTuple(args, "O", &font))
		return NULL;

	if (!((TextPlane_Object *)self)->p)
	{
		PyErr_SetString(PyExc_ValueError, "already destroyed.");
		return NULL;
	}

	if (!Font_Check(font))
	{
		PyErr_SetString(PyExc_TypeError, "must be a Font object.");
		return NULL;
	}

	((TextPlane_Object *)self)->p->SetFont(((Font_Object *)font)->p);

	Py_INCREF(Py_None);
	return Py_None;
}

static PyObject *TextPlane_putString(PyObject *self, PyObject *args, PyObject *kwds)
{
	int x;
	int y;
	int width;
	int height;
	PyObject *pyattr;
	PyObject *pystr;
	int offset = 0;

	static char *kwlist[] = {
		"x",
		"y",
		"width",
		"height",
		"attr",
		"str",
		"offset",
		NULL};

	if (!PyArg_ParseTupleAndKeywords(args, kwds, "iiiiOO|i", kwlist,
									 &x, &y, &width, &height, &pyattr, &pystr,
									 &offset))
	{
		return NULL;
	}

	if (!Attribute_Check(pyattr))
	{
		PyErr_SetString(PyExc_TypeError, "arg 4 must be a Attribute object.");
		return NULL;
	}

	if (!PyUnicode_Check(pystr))
	{
		PyErr_SetString(PyExc_TypeError, "must be unicode.");
		return NULL;
	}
	wchar_t *str = PyUnicode_AsWideCharString(pystr, NULL);
	if (!str)
		return NULL;

	if (!((TextPlane_Object *)self)->p)
	{
		PyMem_Free(str);
		PyErr_SetString(PyExc_ValueError, "already destroyed.");
		return NULL;
	}

	TextPlane *textPlane = ((TextPlane_Object *)self)->p;
	if (!textPlane->font)
	{
		PyMem_Free(str);
		PyErr_SetString(PyExc_ValueError, "font is not set.");
		return NULL;
	}

	try
	{
		textPlane->PutString(x, y, width, height, ((Attribute_Object *)pyattr)->attr, str, offset);
	}
	catch (const std::bad_alloc &)
	{
		PyMem_Free(str);
		return PyErr_NoMemory();
	}
	PyMem_Free(str);
	if (PyErr_Occurred())
		return NULL;

	Py_INCREF(Py_None);
	return Py_None;
}

static PyObject *TextPlane_scroll(PyObject *self, PyObject *args)
{
	int x, y, width, height, delta_x, delta_y;

	if (!PyArg_ParseTuple(args, "iiiiii", &x, &y, &width, &height, &delta_x, &delta_y))
		return NULL;

	if (!((TextPlane_Object *)self)->p)
	{
		PyErr_SetString(PyExc_ValueError, "already destroyed.");
		return NULL;
	}

	TextPlane *textPlane = ((TextPlane_Object *)self)->p;
	if (!textPlane->font)
	{
		PyErr_SetString(PyExc_ValueError, "font is not set.");
		return NULL;
	}

	if (x < 0 || y < 0 || width < 0 || height < 0)
	{
		PyErr_SetString(PyExc_ValueError, "scroll coordinates and dimensions must be nonnegative.");
		return NULL;
	}
	if (width == 0 || height == 0)
		Py_RETURN_NONE;

	long long right = (long long)x + width;
	long long bottom = (long long)y + height;
	long long dest_x = (long long)x + delta_x;
	long long dest_y = (long long)y + delta_y;
	long long dest_right = right + delta_x;
	long long dest_bottom = bottom + delta_y;
	if (dest_x < 0 || dest_y < 0)
	{
		PyErr_SetString(PyExc_ValueError, "scroll destination must be nonnegative.");
		return NULL;
	}
	if (right > INT_MAX || bottom > INT_MAX || dest_right > INT_MAX || dest_bottom > INT_MAX)
	{
		PyErr_SetString(PyExc_OverflowError, "scroll cell coordinates exceed C int range.");
		return NULL;
	}

	// Check the pixel products and translated dirty rectangle before any allocation.
	int cw = textPlane->font->char_width;
	int ch = textPlane->font->char_height;
	if ((std::max)(right, dest_right) * cw > INT_MAX ||
		(std::max)(bottom, dest_bottom) * ch > INT_MAX ||
		dest_right * cw + textPlane->x > INT_MAX ||
		dest_bottom * ch + textPlane->y > INT_MAX)
	{
		PyErr_SetString(PyExc_OverflowError, "scroll pixel coordinates exceed C int range.");
		return NULL;
	}
	if (delta_x == 0 && delta_y == 0)
		Py_RETURN_NONE;

	try
	{
		textPlane->Scroll(x, y, width, height, delta_x, delta_y);
	}
	catch (const std::bad_alloc &)
	{
		return PyErr_NoMemory();
	}

	Py_INCREF(Py_None);
	return Py_None;
}

static PyObject *TextPlane_getCharSize(PyObject *self, PyObject *args)
{
	if (!PyArg_ParseTuple(args, ""))
		return NULL;

	if (!((TextPlane_Object *)self)->p)
	{
		PyErr_SetString(PyExc_ValueError, "already destroyed.");
		return NULL;
	}

	TextPlane *textPlane = ((TextPlane_Object *)self)->p;
	if (!textPlane->font)
	{
		PyErr_SetString(PyExc_ValueError, "font is not set.");
		return NULL;
	}

	PyObject *pyret = Py_BuildValue("(ii)", textPlane->font->char_width, textPlane->font->char_height);
	return pyret;
}

static PyObject *TextPlane_charToScreen(PyObject *self, PyObject *args)
{
	int x;
	int y;

	if (!PyArg_ParseTuple(args, "ii", &x, &y))
		return NULL;

	if (!((TextPlane_Object *)self)->p)
	{
		PyErr_SetString(PyExc_ValueError, "already destroyed.");
		return NULL;
	}

	TextPlane *textPlane = ((TextPlane_Object *)self)->p;
	if (!textPlane->font)
	{
		PyErr_SetString(PyExc_ValueError, "font is not set.");
		return NULL;
	}

	POINT point;
	point.x = x * textPlane->font->char_width + textPlane->x;
	point.y = y * textPlane->font->char_height + textPlane->y;

	ClientToScreen(textPlane->window->hwnd, &point);

	PyObject *pyret = Py_BuildValue("(ii)", point.x, point.y);
	return pyret;
}

static PyObject *TextPlane_charToClient(PyObject *self, PyObject *args)
{
	int x;
	int y;

	if (!PyArg_ParseTuple(args, "ii", &x, &y))
		return NULL;

	if (!((TextPlane_Object *)self)->p)
	{
		PyErr_SetString(PyExc_ValueError, "already destroyed.");
		return NULL;
	}

	TextPlane *textPlane = ((TextPlane_Object *)self)->p;
	if (!textPlane->font)
	{
		PyErr_SetString(PyExc_ValueError, "font is not set.");
		return NULL;
	}

	POINT point;
	point.x = x * textPlane->font->char_width + textPlane->x;
	point.y = y * textPlane->font->char_height + textPlane->y;

	PyObject *pyret = Py_BuildValue("(ii)", point.x, point.y);
	return pyret;
}

static PyObject *TextPlane_getStringWidth(PyObject *self, PyObject *args)
{
	PyObject *pystr;
	int tab_width = 4;
	int offset = 0;

	if (!PyArg_ParseTuple(args, "O|ii", &pystr, &tab_width, &offset))
		return NULL;

	std::wstring str;
	if (!PythonUtil::PyStringToWideString(pystr, &str))
	{
		return NULL;
	}

	if (!((TextPlane_Object *)self)->p)
	{
		PyErr_SetString(PyExc_ValueError, "already destroyed.");
		return NULL;
	}

	TextPlane *textPlane = ((TextPlane_Object *)self)->p;
	if (!textPlane->font)
	{
		PyErr_SetString(PyExc_ValueError, "font is not set.");
		return NULL;
	}

	if (tab_width <= 0)
	{
		PyErr_SetString(PyExc_ValueError, "tab_width must be positive.");
		return NULL;
	}

	int width = textPlane->GetStringWidth(str.c_str(), tab_width, offset);
	if (width < 0)
	{
		PyErr_SetString(PyExc_OverflowError, "string width exceeds C int range.");
		return NULL;
	}

	PyObject *pyret = Py_BuildValue("i", width);
	return pyret;
}

static PyObject *TextPlane_getStringColumns(PyObject *self, PyObject *args)
{
	PyObject *pystr;
	int tab_width = 4;
	int offset = 0;

	if (!PyArg_ParseTuple(args, "O|ii", &pystr, &tab_width, &offset))
		return NULL;

	if (!PyUnicode_Check(pystr))
	{
		PyErr_SetString(PyExc_TypeError, "must be unicode.");
		return NULL;
	}
	wchar_t *str = PyUnicode_AsWideCharString(pystr, NULL);
	if (!str)
	{
		return NULL;
	}

	if (!((TextPlane_Object *)self)->p)
	{
		PyMem_Free(str);
		PyErr_SetString(PyExc_ValueError, "already destroyed.");
		return NULL;
	}

	TextPlane *textPlane = ((TextPlane_Object *)self)->p;
	if (!textPlane->font)
	{
		PyMem_Free(str);
		PyErr_SetString(PyExc_ValueError, "font is not set.");
		return NULL;
	}

	if (tab_width <= 0)
	{
		PyMem_Free(str);
		PyErr_SetString(PyExc_ValueError, "tab_width must be positive.");
		return NULL;
	}

	size_t length = std::wcslen(str);
	if (length >= INT_MAX)
	{
		PyMem_Free(str);
		PyErr_SetString(PyExc_OverflowError, "string length exceeds C int range.");
		return NULL;
	}
	int num = (int)length + 1;
	int *columns = new (std::nothrow) int[num];
	if (!columns)
	{
		PyMem_Free(str);
		return PyErr_NoMemory();
	}

	int width = textPlane->GetStringWidth(str, tab_width, offset, columns);
	PyMem_Free(str);
	if (width < 0)
	{
		delete[] columns;
		PyErr_SetString(PyExc_OverflowError, "string width exceeds C int range.");
		return NULL;
	}

	PyObject *pyret = PyTuple_New(num);
	if (!pyret)
	{
		delete[] columns;
		return NULL;
	}
	for (int i = 0; i < num; ++i)
	{
		PyObject *item = PyLong_FromLong(columns[i]);
		if (!item)
		{
			Py_DECREF(pyret);
			delete[] columns;
			return NULL;
		}
		PyTuple_SET_ITEM(pyret, i, item);
	}
	delete[] columns;

	return pyret;
}

static PyObject *TextPlane_setCaretPosition(PyObject *self, PyObject *args)
{
	int x;
	int y;

	if (!PyArg_ParseTuple(args, "ii", &x, &y))
		return NULL;

	if (!((TextPlane_Object *)self)->p)
	{
		PyErr_SetString(PyExc_ValueError, "already destroyed.");
		return NULL;
	}

	TextPlane *textPlane = ((TextPlane_Object *)self)->p;
	if (!textPlane->font)
	{
		PyErr_SetString(PyExc_ValueError, "font is not set.");
		return NULL;
	}

	textPlane->SetCaretPosition(x, y);

	Py_INCREF(Py_None);
	return Py_None;
}

static PyMethodDef TextPlane_methods[] = {

	{"destroy", TextPlane_destroy, METH_VARARGS, ""},

	{"show", TextPlane_show, METH_VARARGS, ""},

	{"getPosition", TextPlane_getPosition, METH_VARARGS, ""},
	{"getSize", TextPlane_getSize, METH_VARARGS, ""},
	{"getPriority", TextPlane_getPriority, METH_VARARGS, ""},
	{"getFont", TextPlane_getFont, METH_VARARGS, ""},

	{"setPosition", TextPlane_setPosition, METH_VARARGS, ""},
	{"setSize", TextPlane_setSize, METH_VARARGS, ""},
	{"setPriority", TextPlane_setPriority, METH_VARARGS, ""},
	{"setFont", TextPlane_setFont, METH_VARARGS, ""},

	{"putString", (PyCFunction)TextPlane_putString, METH_VARARGS | METH_KEYWORDS, ""},
	{"scroll", TextPlane_scroll, METH_VARARGS, ""},

	{"getCharSize", TextPlane_getCharSize, METH_VARARGS, ""},
	{"charToScreen", TextPlane_charToScreen, METH_VARARGS, ""},
	{"charToClient", TextPlane_charToClient, METH_VARARGS, ""},
	{"getStringWidth", TextPlane_getStringWidth, METH_VARARGS, ""},
	{"getStringColumns", TextPlane_getStringColumns, METH_VARARGS, ""},

	{"setCaretPosition", TextPlane_setCaretPosition, METH_VARARGS, ""},

	{NULL, NULL}};

PyTypeObject TextPlane_Type = {
	PyVarObject_HEAD_INIT(NULL, 0) "TextPlane", /* tp_name */
	sizeof(TextPlane_Object),					/* tp_basicsize */
	0,											/* tp_itemsize */
	TextPlane_dealloc,							/* tp_dealloc */
	0,											/* tp_print */
	0,											/* tp_getattr */
	0,											/* tp_setattr */
	0,											/* tp_reserved */
	0,											/* tp_repr */
	0,											/* tp_as_number */
	0,											/* tp_as_sequence */
	0,											/* tp_as_mapping */
	0,											/* tp_hash */
	0,											/* tp_call */
	0,											/* tp_str */
	PyObject_GenericGetAttr,					/* tp_getattro */
	PyObject_GenericSetAttr,					/* tp_setattro */
	0,											/* tp_as_buffer */
	Py_TPFLAGS_DEFAULT | Py_TPFLAGS_BASETYPE,	/* tp_flags */
	"",											/* tp_doc */
	0,											/* tp_traverse */
	0,											/* tp_clear */
	0,											/* tp_richcompare */
	0,											/* tp_weaklistoffset */
	0,											/* tp_iter */
	0,											/* tp_iternext */
	TextPlane_methods,							/* tp_methods */
	0,											/* tp_members */
	0,											/* tp_getset */
	0,											/* tp_base */
	0,											/* tp_dict */
	0,											/* tp_descr_get */
	0,											/* tp_descr_set */
	0,											/* tp_dictoffset */
	TextPlane_init,								/* tp_init */
	0,											/* tp_alloc */
	PyType_GenericNew,							/* tp_new */
	0,											/* tp_free */
};

// ----------------------------------------------------------------------------
//
// ----------------------------------------------------------------------------

static int MenuNode_init(PyObject *self, PyObject *args, PyObject *kwds)
{
	PyObject *pystr_name = NULL;
	PyObject *pystr_text = NULL;
	PyObject *command = NULL;
	PyObject *visible = NULL;
	PyObject *enabled = NULL;
	PyObject *checked = NULL;
	PyObject *items = NULL;
	int separator = 0;

	static char *kwlist[] = {
		"name",
		"text",
		"command",
		"visible",
		"enabled",
		"checked",
		"items",
		"separator",
		NULL};

	if (!PyArg_ParseTupleAndKeywords(args, kwds, "|OOOOOOOi", kwlist,
									 &pystr_name,
									 &pystr_text,
									 &command,
									 &visible,
									 &enabled,
									 &checked,
									 &items,
									 &separator))
	{
		return -1;
	}

	std::wstring str_name;
	if (pystr_name)
	{
		if (!PythonUtil::PyStringToWideString(pystr_name, &str_name))
		{
			return -1;
		}
	}

	std::wstring str_text;
	if (pystr_text)
	{
		if (!PythonUtil::PyStringToWideString(pystr_text, &str_text))
		{
			return -1;
		}
	}

	MenuNode::Param param;
	if (separator)
	{
		param.separator = true;
	}
	param.name = str_name;
	param.text = str_text;
	param.command = command;
	param.visible = visible;
	param.enabled = enabled;
	param.checked = checked;
	param.items = items;

	MenuNode *menu_node = new MenuNode(param);
	((MenuNode_Object *)self)->p = menu_node;
	menu_node->AddRef();

	return 0;
}

static void MenuNode_dealloc(PyObject *self)
{
	MenuNode *menu_node = ((MenuNode_Object *)self)->p;
	if (menu_node)
		menu_node->Release();
	self->ob_type->tp_free(self);
}

static PyObject *MenuNode_GetAttrString(PyObject *self, const char *attr_name)
{
	switch (attr_name[0])
	{
	case 'n':
		if (strcmp(attr_name, "name") == 0)
		{
			PyObject *value = Py_BuildValue("u", ((MenuNode_Object *)self)->p->name.c_str());
			return value;
		}
		break;

	case 'i':
		if (strcmp(attr_name, "items") == 0)
		{
			PyObject *value = ((MenuNode_Object *)self)->p->items;
			if (!value)
			{
				value = Py_None;
			}
			Py_INCREF(value);
			return value;
		}
		break;
	}

	PyErr_SetString(PyExc_AttributeError, attr_name);
	return NULL;
}

static int MenuNode_SetAttrString(PyObject *self, const char *attr_name, PyObject *value)
{
	switch (attr_name[0])
	{
	case 'n':
		if (strcmp(attr_name, "name") == 0)
		{
			std::wstring name;
			if (!PythonUtil::PyStringToWideString(value, &name))
			{
				return -1;
			}
			((MenuNode_Object *)self)->p->name = name;
			return 0;
		}
		break;

	case 'i':
		if (strcmp(attr_name, "items") == 0)
		{
			Py_XDECREF(((MenuNode_Object *)self)->p->items);
			((MenuNode_Object *)self)->p->items = value;
			Py_XINCREF(((MenuNode_Object *)self)->p->items);
			return 0;
		}
		break;
	}

	PyErr_SetString(PyExc_AttributeError, attr_name);
	return -1;
}

static PyMethodDef MenuNode_methods[] = {
	{NULL, NULL}};

PyTypeObject MenuNode_Type = {
	PyVarObject_HEAD_INIT(NULL, 0) "MenuNode", /* tp_name */
	sizeof(MenuNode_Object),				   /* tp_basicsize */
	0,										   /* tp_itemsize */
	MenuNode_dealloc,						   /* tp_dealloc */
	0,										   /* tp_print */
	(getattrfunc)MenuNode_GetAttrString,	   /* tp_getattr */
	(setattrfunc)MenuNode_SetAttrString,	   /* tp_setattr */
	0,										   /* tp_reserved */
	0,										   /* tp_repr */
	0,										   /* tp_as_number */
	0,										   /* tp_as_sequence */
	0,										   /* tp_as_mapping */
	0,										   /* tp_hash */
	0,										   /* tp_call */
	0,										   /* tp_str */
	0,										   /* tp_getattro */
	0,										   /* tp_setattro */
	0,										   /* tp_as_buffer */
	Py_TPFLAGS_DEFAULT | Py_TPFLAGS_BASETYPE,  /* tp_flags */
	"",										   /* tp_doc */
	0,										   /* tp_traverse */
	0,										   /* tp_clear */
	0,										   /* tp_richcompare */
	0,										   /* tp_weaklistoffset */
	0,										   /* tp_iter */
	0,										   /* tp_iternext */
	MenuNode_methods,						   /* tp_methods */
	0,										   /* tp_members */
	0,										   /* tp_getset */
	0,										   /* tp_base */
	0,										   /* tp_dict */
	0,										   /* tp_descr_get */
	0,										   /* tp_descr_set */
	0,										   /* tp_dictoffset */
	MenuNode_init,							   /* tp_init */
	0,										   /* tp_alloc */
	PyType_GenericNew,						   /* tp_new */
	0,										   /* tp_free */
};

// ----------------------------------------------------------------------------
//
// ----------------------------------------------------------------------------

static int Window_init(PyObject *self, PyObject *args, PyObject *kwds)
{
	if (((Window_Object *)self)->p)
	{
		PyErr_SetString(PyExc_ValueError, "already initialized.");
		return -1;
	}
	int x = CW_USEDEFAULT;
	int y = CW_USEDEFAULT;
	int width = 100;
	int height = 100;
	int origin = 0;
	PyObject *parent_window = NULL;
	PyObject *pybg_color = NULL;
	PyObject *pyframe_color = NULL;
	PyObject *pycaret0_color = NULL;
	PyObject *pycaret1_color = NULL;
	int border_size = 1;
	PyObject *pytransparency = NULL;
	PyObject *pytransparent_color = NULL;
	int title_bar = 1;
	PyObject *pystr_title = NULL;
	int show = 1;
	int resizable = 1;
	int noframe = 0;
	int minimizebox = 1;
	int maximizebox = 1;
	int caret = 0;
	int sysmenu = 0;
	int tool = 0;
	int ncpaint = 0;
	PyObject *activate_handler = NULL;
	PyObject *close_handler = NULL;
	PyObject *endsession_handler = NULL;
	PyObject *move_handler = NULL;
	PyObject *sizing_handler = NULL;
	PyObject *size_handler = NULL;
	PyObject *dpi_handler = NULL;
	PyObject *dropfiles_handler = NULL;
	PyObject *ipc_handler = NULL;
	PyObject *keydown_handler = NULL;
	PyObject *keyup_handler = NULL;
	PyObject *char_handler = NULL;
	PyObject *lbuttondown_handler = NULL;
	PyObject *lbuttonup_handler = NULL;
	PyObject *mbuttondown_handler = NULL;
	PyObject *mbuttonup_handler = NULL;
	PyObject *rbuttondown_handler = NULL;
	PyObject *rbuttonup_handler = NULL;
	PyObject *lbuttondoubleclick_handler = NULL;
	PyObject *mbuttondoubleclick_handler = NULL;
	PyObject *rbuttondoubleclick_handler = NULL;
	PyObject *mousemove_handler = NULL;
	PyObject *mousewheel_handler = NULL;
	PyObject *nchittest_handler = NULL;

	static char *kwlist[] = {

		"x",
		"y",
		"width",
		"height",
		"origin",

		"parent_window",
		"bg_color",
		"frame_color",
		"caret0_color",
		"caret1_color",

		"border_size",
		"transparency",
		"transparent_color",
		"title_bar",
		"title",

		"show",
		"resizable",
		"noframe",
		"minimizebox",
		"maximizebox",
		"caret",
		"sysmenu",
		"tool",
		"ncpaint",

		"activate_handler",
		"close_handler",
		"endsession_handler",
		"move_handler",
		"sizing_handler",
		"size_handler",
		"dpi_handler",
		"dropfiles_handler",
		"ipc_handler",
		"keydown_handler",
		"keyup_handler",
		"char_handler",
		"lbuttondown_handler",
		"lbuttonup_handler",
		"mbuttondown_handler",
		"mbuttonup_handler",
		"rbuttondown_handler",
		"rbuttonup_handler",
		"lbuttondoubleclick_handler",
		"mbuttondoubleclick_handler",
		"rbuttondoubleclick_handler",
		"mousemove_handler",
		"mousewheel_handler",
		"nchittest_handler",
		NULL};

	if (!PyArg_ParseTupleAndKeywords(args, kwds,
									 "|iiiii"
									 "OOOOO"
									 "iOOiO"
									 "iiiiiiiii"
									 "OOOOOOOOOOOOOOOOOOOOOOOO",
									 kwlist,

									 &x,
									 &y,
									 &width,
									 &height,
									 &origin,

									 &parent_window,
									 &pybg_color,
									 &pyframe_color,
									 &pycaret0_color,
									 &pycaret1_color,

									 &border_size,
									 &pytransparency,
									 &pytransparent_color,
									 &title_bar,
									 &pystr_title,

									 &show,
									 &resizable,
									 &noframe,
									 &minimizebox,
									 &maximizebox,
									 &caret,
									 &sysmenu,
									 &tool,
									 &ncpaint,

									 &activate_handler,
									 &close_handler,
									 &endsession_handler,
									 &move_handler,
									 &sizing_handler,
									 &size_handler,
									 &dpi_handler,
									 &dropfiles_handler,
									 &ipc_handler,
									 &keydown_handler,
									 &keyup_handler,
									 &char_handler,
									 &lbuttondown_handler,
									 &lbuttonup_handler,
									 &mbuttondown_handler,
									 &mbuttonup_handler,
									 &rbuttondown_handler,
									 &rbuttonup_handler,
									 &lbuttondoubleclick_handler,
									 &mbuttondoubleclick_handler,
									 &rbuttondoubleclick_handler,
									 &mousemove_handler,
									 &mousewheel_handler,
									 &nchittest_handler))
	{
		return -1;
	}

	if (parent_window != 0 && !PyLong_Check(parent_window) && !Window_Check(parent_window))
	{
		PyErr_SetString(PyExc_TypeError, "must be HWND or Window object.");
		return -1;
	}

	std::wstring str_title;
	if (pystr_title)
	{
		if (!PythonUtil::PyStringToWideString(pystr_title, &str_title))
		{
			return -1;
		}
	}

	Window::Param param;
	param.is_winpos_given = true;
	param.winpos_x = x;
	param.winpos_y = y;
	param.winsize_w = width;
	param.winsize_h = height;
	param.origin = origin;
	if (!parent_window)
	{
		param.parent_window = NULL;
		param.parent_window_hwnd = NULL;
	}
	else if (PyLong_Check(parent_window))
	{
		param.parent_window = NULL;
		size_t hwnd_value = PyLong_AsSize_t(parent_window);
		if (PyErr_Occurred())
			return -1;
		param.parent_window_hwnd = reinterpret_cast<HWND>(hwnd_value);
	}
	else
	{
		param.parent_window = ((Window_Object *)parent_window)->p;
		if (!param.parent_window)
		{
			PyErr_SetString(PyExc_ValueError, "parent window is already destroyed or uninitialized.");
			return -1;
		}
		param.parent_window_hwnd = param.parent_window->hwnd;
	}
	if (pybg_color)
	{
		int r, g, b;
		if (!PyArg_ParseTuple(pybg_color, "iii", &r, &g, &b))
			return -1;
		param.bg_color = RGB(r, g, b);
	}
	if (pyframe_color)
	{
		int r, g, b;
		if (!PyArg_ParseTuple(pyframe_color, "iii", &r, &g, &b))
			return -1;
		param.frame_color = RGB(r, g, b);
	}
	if (pycaret0_color)
	{
		int r, g, b;
		if (!PyArg_ParseTuple(pycaret0_color, "iii", &r, &g, &b))
			return -1;
		param.caret0_color = RGB(r, g, b);
	}
	if (pycaret1_color)
	{
		int r, g, b;
		if (!PyArg_ParseTuple(pycaret1_color, "iii", &r, &g, &b))
			return -1;
		param.caret1_color = RGB(r, g, b);
	}
	param.border_size = border_size;

	if (pytransparency && PyLong_Check(pytransparency))
	{
		param.transparency = PyLong_AS_LONG(pytransparency);
		param.is_transparency_given = true;
	}

	if (pytransparent_color)
	{
		int r, g, b;
		if (!PyArg_ParseTuple(pytransparent_color, "iii", &r, &g, &b))
			return -1;
		param.transparent_color = RGB(r, g, b);
		param.is_transparent_color_given = true;
	}
	param.title_bar = title_bar != 0;
	param.title = str_title;
	param.show = show != 0;
	param.resizable = resizable != 0;
	param.noframe = noframe != 0;
	param.minimizebox = minimizebox != 0;
	param.maximizebox = maximizebox != 0;
	param.caret = caret != 0;
	param.sysmenu = sysmenu != 0;
	param.tool = tool != 0;
	param.ncpaint = ncpaint != 0;
	param.activate_handler = activate_handler;
	param.close_handler = close_handler;
	param.endsession_handler = endsession_handler;
	param.move_handler = move_handler;
	param.sizing_handler = sizing_handler;
	param.size_handler = size_handler;
	param.dpi_handler = dpi_handler;
	param.dropfiles_handler = dropfiles_handler;
	param.ipc_handler = ipc_handler;
	param.keydown_handler = keydown_handler;
	param.keyup_handler = keyup_handler;
	param.char_handler = char_handler;
	param.lbuttondown_handler = lbuttondown_handler;
	param.lbuttonup_handler = lbuttonup_handler;
	param.mbuttondown_handler = mbuttondown_handler;
	param.mbuttonup_handler = mbuttonup_handler;
	param.rbuttondown_handler = rbuttondown_handler;
	param.rbuttonup_handler = rbuttonup_handler;
	param.lbuttondoubleclick_handler = lbuttondoubleclick_handler;
	param.mbuttondoubleclick_handler = mbuttondoubleclick_handler;
	param.rbuttondoubleclick_handler = rbuttondoubleclick_handler;
	param.mousemove_handler = mousemove_handler;
	param.mousewheel_handler = mousewheel_handler;
	param.nchittest_handler = nchittest_handler;

	Window *window;
	try
	{
		window = new Window(param);
	}
	catch (const std::bad_alloc &)
	{
		PyErr_NoMemory();
		return -1;
	}
	if (!window->_createWindow(param))
	{
		PyObject *error = PyErr_GetRaisedException();
		delete window;
		PyErr_SetRaisedException(error);
		return -1;
	}
	window->creating = false;

	window->SetPyObject(self);

	((Window_Object *)self)->p = window;

	return 0;
}

static void Window_dealloc(PyObject *self)
{
	Window *window = ((Window_Object *)self)->p;
	if (window)
	{
		window->SetPyObject(NULL);
	}

	self->ob_type->tp_free(self);
}

static PyObject *Window_getHWND(PyObject *self, PyObject *args)
{
	if (!PyArg_ParseTuple(args, ""))
		return NULL;

	if (!((Window_Object *)self)->p)
	{
		PyErr_SetString(PyExc_ValueError, "already destroyed.");
		return NULL;
	}

	Window *window = ((Window_Object *)self)->p;

	HWND hwnd = window->getHWND();

	PyObject *pyret = PyLong_FromVoidPtr(hwnd);
	return pyret;
}

static PyObject *Window_getHINSTANCE(PyObject *self, PyObject *args)
{
	if (!PyArg_ParseTuple(args, ""))
		return NULL;

	if (!((Window_Object *)self)->p)
	{
		PyErr_SetString(PyExc_ValueError, "already destroyed.");
		return NULL;
	}

	Window *window = ((Window_Object *)self)->p;

	HINSTANCE hinstance = GetModuleHandle(NULL);

	PyObject *pyret = PyLong_FromVoidPtr(hinstance);
	return pyret;
}

static PyObject *Window_show(PyObject *self, PyObject *args)
{
	int show;
	int activate = 1;

	if (!PyArg_ParseTuple(args, "i|i", &show, &activate))
		return NULL;

	if (!((Window_Object *)self)->p)
	{
		PyErr_SetString(PyExc_ValueError, "already destroyed.");
		return NULL;
	}

	Window *window = ((Window_Object *)self)->p;

	window->show(show != 0, activate != 0);

	Py_INCREF(Py_None);
	return Py_None;
}

static PyObject *Window_enable(PyObject *self, PyObject *args)
{
	int enable;

	if (!PyArg_ParseTuple(args, "i", &enable))
		return NULL;

	if (!((Window_Object *)self)->p)
	{
		PyErr_SetString(PyExc_ValueError, "already destroyed.");
		return NULL;
	}

	Window *window = ((Window_Object *)self)->p;

	window->enable(enable != 0);

	Py_INCREF(Py_None);
	return Py_None;
}

static PyObject *Window_destroy(PyObject *self, PyObject *args)
{
	if (!PyArg_ParseTuple(args, ""))
		return NULL;

	if (!((Window_Object *)self)->p)
	{
		PyErr_SetString(PyExc_ValueError, "already destroyed.");
		return NULL;
	}

	Window *window = ((Window_Object *)self)->p;

	if (!window->destroy())
		return NULL;

	Py_INCREF(Py_None);
	return Py_None;
}

static PyObject *Window_activate(PyObject *self, PyObject *args)
{
	if (!PyArg_ParseTuple(args, ""))
		return NULL;

	if (!((Window_Object *)self)->p)
	{
		PyErr_SetString(PyExc_ValueError, "already destroyed.");
		return NULL;
	}

	Window *window = ((Window_Object *)self)->p;

	window->activate();

	Py_INCREF(Py_None);
	return Py_None;
}

static PyObject *Window_inactivate(PyObject *self, PyObject *args)
{
	if (!PyArg_ParseTuple(args, ""))
		return NULL;

	if (!((Window_Object *)self)->p)
	{
		PyErr_SetString(PyExc_ValueError, "already destroyed.");
		return NULL;
	}

	Window *window = ((Window_Object *)self)->p;

	window->inactivate();

	Py_INCREF(Py_None);
	return Py_None;
}

static PyObject *Window_foreground(PyObject *self, PyObject *args)
{
	if (!PyArg_ParseTuple(args, ""))
		return NULL;

	if (!((Window_Object *)self)->p)
	{
		PyErr_SetString(PyExc_ValueError, "already destroyed.");
		return NULL;
	}

	Window *window = ((Window_Object *)self)->p;

	window->foreground();

	Py_INCREF(Py_None);
	return Py_None;
}

static PyObject *Window_restore(PyObject *self, PyObject *args)
{
	if (!PyArg_ParseTuple(args, ""))
		return NULL;

	if (!((Window_Object *)self)->p)
	{
		PyErr_SetString(PyExc_ValueError, "already destroyed.");
		return NULL;
	}

	Window *window = ((Window_Object *)self)->p;

	window->restore();

	Py_INCREF(Py_None);
	return Py_None;
}

static PyObject *Window_maximize(PyObject *self, PyObject *args)
{
	if (!PyArg_ParseTuple(args, ""))
		return NULL;

	if (!((Window_Object *)self)->p)
	{
		PyErr_SetString(PyExc_ValueError, "already destroyed.");
		return NULL;
	}

	Window *window = ((Window_Object *)self)->p;

	window->maximize();

	Py_INCREF(Py_None);
	return Py_None;
}

static PyObject *Window_minimize(PyObject *self, PyObject *args)
{
	if (!PyArg_ParseTuple(args, ""))
		return NULL;

	if (!((Window_Object *)self)->p)
	{
		PyErr_SetString(PyExc_ValueError, "already destroyed.");
		return NULL;
	}

	Window *window = ((Window_Object *)self)->p;

	window->minimize();

	Py_INCREF(Py_None);
	return Py_None;
}

static PyObject *Window_topmost(PyObject *self, PyObject *args)
{
	int topmost;

	if (!PyArg_ParseTuple(args, "i", &topmost))
		return NULL;

	if (!((Window_Object *)self)->p)
	{
		PyErr_SetString(PyExc_ValueError, "already destroyed.");
		return NULL;
	}

	Window *window = ((Window_Object *)self)->p;

	window->topmost(topmost != 0);

	Py_INCREF(Py_None);
	return Py_None;
}

static PyObject *Window_isEnabled(PyObject *self, PyObject *args)
{
	if (!PyArg_ParseTuple(args, ""))
		return NULL;

	if (!((Window_Object *)self)->p)
	{
		PyErr_SetString(PyExc_ValueError, "already destroyed.");
		return NULL;
	}

	Window *window = ((Window_Object *)self)->p;

	if (window->isEnabled())
	{
		Py_INCREF(Py_True);
		return Py_True;
	}
	else
	{
		Py_INCREF(Py_False);
		return Py_False;
	}
}

static PyObject *Window_isVisible(PyObject *self, PyObject *args)
{
	if (!PyArg_ParseTuple(args, ""))
		return NULL;

	if (!((Window_Object *)self)->p)
	{
		PyErr_SetString(PyExc_ValueError, "already destroyed.");
		return NULL;
	}

	Window *window = ((Window_Object *)self)->p;

	if (window->isVisible())
	{
		Py_INCREF(Py_True);
		return Py_True;
	}
	else
	{
		Py_INCREF(Py_False);
		return Py_False;
	}
}

static PyObject *Window_isMaximized(PyObject *self, PyObject *args)
{
	if (!PyArg_ParseTuple(args, ""))
		return NULL;

	if (!((Window_Object *)self)->p)
	{
		PyErr_SetString(PyExc_ValueError, "already destroyed.");
		return NULL;
	}

	Window *window = ((Window_Object *)self)->p;

	if (window->isMaximized())
	{
		Py_INCREF(Py_True);
		return Py_True;
	}
	else
	{
		Py_INCREF(Py_False);
		return Py_False;
	}
}

static PyObject *Window_isMinimized(PyObject *self, PyObject *args)
{
	if (!PyArg_ParseTuple(args, ""))
		return NULL;

	if (!((Window_Object *)self)->p)
	{
		PyErr_SetString(PyExc_ValueError, "already destroyed.");
		return NULL;
	}

	Window *window = ((Window_Object *)self)->p;

	if (window->isMinimized())
	{
		Py_INCREF(Py_True);
		return Py_True;
	}
	else
	{
		Py_INCREF(Py_False);
		return Py_False;
	}
}

static PyObject *Window_isActive(PyObject *self, PyObject *args)
{
	if (!PyArg_ParseTuple(args, ""))
		return NULL;

	if (!((Window_Object *)self)->p)
	{
		PyErr_SetString(PyExc_ValueError, "already destroyed.");
		return NULL;
	}

	Window *window = ((Window_Object *)self)->p;

	if (window->isActive())
	{
		Py_INCREF(Py_True);
		return Py_True;
	}
	else
	{
		Py_INCREF(Py_False);
		return Py_False;
	}
}

static PyObject *Window_isForeground(PyObject *self, PyObject *args)
{
	if (!PyArg_ParseTuple(args, ""))
		return NULL;

	if (!((Window_Object *)self)->p)
	{
		PyErr_SetString(PyExc_ValueError, "already destroyed.");
		return NULL;
	}

	Window *window = ((Window_Object *)self)->p;

	if (window->isForeground())
	{
		Py_INCREF(Py_True);
		return Py_True;
	}
	else
	{
		Py_INCREF(Py_False);
		return Py_False;
	}
}

static PyObject *Window_clear(PyObject *self, PyObject *args)
{
	if (!PyArg_ParseTuple(args, ""))
		return NULL;

	if (!((Window_Object *)self)->p)
	{
		PyErr_SetString(PyExc_ValueError, "already destroyed.");
		return NULL;
	}

	Window *window = ((Window_Object *)self)->p;

	Window::Reference reference(window);
	window->clear();

	Py_INCREF(Py_None);
	return Py_None;
}

static PyObject *Window_flushPaint(PyObject *self, PyObject *args)
{
	if (!PyArg_ParseTuple(args, ""))
		return NULL;

	if (!((Window_Object *)self)->p)
	{
		PyErr_SetString(PyExc_ValueError, "already destroyed.");
		return NULL;
	}

	Window *window = ((Window_Object *)self)->p;

	window->flushPaint();

	Py_INCREF(Py_None);
	return Py_None;
}

// Copy the offscreen buffer directly to the window for drawing diagnostics.
static PyObject *Window_bitBlt(PyObject *self, PyObject *args)
{
	if (!PyArg_ParseTuple(args, ""))
		return NULL;

	if (!((Window_Object *)self)->p)
	{
		PyErr_SetString(PyExc_ValueError, "already destroyed.");
		return NULL;
	}

	Window *window = ((Window_Object *)self)->p;

	HDC hDC = GetDC(window->hwnd);

	RECT client_rect;
	GetClientRect(window->hwnd, &client_rect);

	BitBlt(
		hDC,
		client_rect.left,
		client_rect.top,
		client_rect.right - client_rect.left,
		client_rect.bottom - client_rect.top,
		window->offscreen_dc,
		client_rect.left,
		client_rect.top,
		SRCCOPY);

	ReleaseDC(window->hwnd, hDC);

	Py_INCREF(Py_None);
	return Py_None;
}

static PyObject *Window_setImeRect(PyObject *self, PyObject *args)
{
	PyObject *pyrect;

	if (!PyArg_ParseTuple(args, "O", &pyrect))
		return NULL;

	if (!((Window_Object *)self)->p)
	{
		PyErr_SetString(PyExc_ValueError, "already destroyed.");
		return NULL;
	}

	Window *window = ((Window_Object *)self)->p;

	RECT rect;

	if (pyrect == Py_None)
	{
		memset(&rect, 0, sizeof(rect));
		window->setImeRect(rect);
	}
	else if (pyrect && PySequence_Check(pyrect))
	{
		if (!PyArg_ParseTuple(pyrect, "iiii", &rect.left, &rect.top, &rect.right, &rect.bottom))
			return NULL;
		window->setImeRect(rect);
	}
	else
	{
		PyErr_SetString(PyExc_TypeError, "invalid argument type.");
		return NULL;
	}

	Py_INCREF(Py_None);
	return Py_None;
}

static PyObject *Window_enableIme(PyObject *self, PyObject *args)
{
	int enable;

	if (!PyArg_ParseTuple(args, "i", &enable))
		return NULL;

	if (!((Window_Object *)self)->p)
	{
		PyErr_SetString(PyExc_ValueError, "already destroyed.");
		return NULL;
	}

	Window *window = ((Window_Object *)self)->p;

	window->enableIme(enable != 0);

	Py_INCREF(Py_None);
	return Py_None;
}

static PyObject *Window_setPositionAndSize(PyObject *self, PyObject *args, PyObject *kwds)
{
	int x;
	int y;
	int width;
	int height;
	int origin;

	static char *kwlist[] = {
		"x",
		"y",
		"width",
		"height",
		"origin",
		NULL};

	if (!PyArg_ParseTupleAndKeywords(args, kwds, "iiiii", kwlist,
									 &x,
									 &y,
									 &width,
									 &height,
									 &origin))
	{
		return NULL;
	}

	if (!((Window_Object *)self)->p)
	{
		PyErr_SetString(PyExc_ValueError, "already destroyed.");
		return NULL;
	}

	Window *window = ((Window_Object *)self)->p;

	window->setPositionAndSize(x, y, width, height, origin);

	Py_INCREF(Py_None);
	return Py_None;
}

static PyObject *Window_messageLoop(PyObject *self, PyObject *args, PyObject *kwds)
{
	PyObject *continue_cond_func = NULL;

	static char *kwlist[] = {
		"continue_cond_func",
		NULL};

	if (!PyArg_ParseTupleAndKeywords(args, kwds, "|O", kwlist,
									 &continue_cond_func))
	{
		return NULL;
	}

	if (!((Window_Object *)self)->p)
	{
		PyErr_SetString(PyExc_ValueError, "already destroyed.");
		return NULL;
	}

	for (;;)
	{
		// Process all pending messages.
		MSG msg;
		while (PeekMessage(&msg, NULL, 0, 0, PM_REMOVE))
		{
			if (msg.message == WM_QUIT)
			{
				goto end;
			}

			TranslateMessage(&msg);
			DispatchMessage(&msg);
		}

		// Check whether to exit the message loop only after draining pending messages.
		{
			Window *window = ((Window_Object *)self)->p;

			if (window == NULL)
			{
				goto end;
			}

			if (window->quit_requested)
			{
				window->quit_requested = false;
				goto end;
			}

			if (continue_cond_func)
			{
				PyObject *pyresult = PyObject_CallNoArgs(continue_cond_func);
				if (pyresult)
				{
					int result;
					int parsed = PyArg_Parse(pyresult, "i", &result);
					Py_DECREF(pyresult);
					if (!parsed)
					{
						PyErr_Print();
					}
					if (parsed && !result)
					{
						goto end;
					}
				}
				else
				{
					PyErr_Print();
				}
			}
		}

		if (!((Window_Object *)self)->p)
			goto end;

		Py_BEGIN_ALLOW_THREADS

		WaitMessage();

		Py_END_ALLOW_THREADS
	}

end:

	Py_INCREF(Py_None);
	return Py_None;
}

static PyObject *Window_removeKeyMessage(PyObject *self, PyObject *args)
{
	if (!PyArg_ParseTuple(args, ""))
		return NULL;

	if (!((Window_Object *)self)->p)
	{
		PyErr_SetString(PyExc_ValueError, "already destroyed.");
		return NULL;
	}

	MSG msg;
	while (PeekMessage(&msg, NULL, WM_KEYFIRST, WM_KEYLAST, PM_REMOVE))
	{
	}

	Py_INCREF(Py_None);
	return Py_None;
}

static PyObject *Window_quit(PyObject *self, PyObject *args)
{
	if (!PyArg_ParseTuple(args, ""))
		return NULL;

	if (!((Window_Object *)self)->p)
	{
		PyErr_SetString(PyExc_ValueError, "already destroyed.");
		return NULL;
	}

	Window *window = ((Window_Object *)self)->p;

	window->quit_requested = true;

	Py_INCREF(Py_None);
	return Py_None;
}

static PyObject *Window_getWindowRect(PyObject *self, PyObject *args)
{
	if (!PyArg_ParseTuple(args, ""))
		return NULL;

	if (!((Window_Object *)self)->p)
	{
		PyErr_SetString(PyExc_ValueError, "already destroyed.");
		return NULL;
	}

	Window *window = ((Window_Object *)self)->p;

	RECT rect;
	window->getWindowRect(&rect);

	PyObject *pyret = Py_BuildValue("(iiii)", rect.left, rect.top, rect.right, rect.bottom);
	return pyret;
}

static PyObject *Window_getClientSize(PyObject *self, PyObject *args)
{
	if (!PyArg_ParseTuple(args, ""))
		return NULL;

	if (!((Window_Object *)self)->p)
	{
		PyErr_SetString(PyExc_ValueError, "already destroyed.");
		return NULL;
	}

	Window *window = ((Window_Object *)self)->p;

	RECT rect;
	::GetClientRect(window->hwnd, &rect);

	PyObject *pyret = Py_BuildValue("(ii)", rect.right - rect.left, rect.bottom - rect.top);
	return pyret;
}

static PyObject *Window_getNormalWindowRect(PyObject *self, PyObject *args)
{
	if (!PyArg_ParseTuple(args, ""))
		return NULL;

	if (!((Window_Object *)self)->p)
	{
		PyErr_SetString(PyExc_ValueError, "already destroyed.");
		return NULL;
	}

	Window *window = ((Window_Object *)self)->p;

	RECT rect;
	window->getNormalWindowRect(&rect);

	PyObject *pyret = Py_BuildValue("(iiii)", rect.left, rect.top, rect.right, rect.bottom);
	return pyret;
}

static PyObject *Window_getNormalClientSize(PyObject *self, PyObject *args)
{
	if (!PyArg_ParseTuple(args, ""))
		return NULL;

	if (!((Window_Object *)self)->p)
	{
		PyErr_SetString(PyExc_ValueError, "already destroyed.");
		return NULL;
	}

	Window *window = ((Window_Object *)self)->p;

	SIZE size;
	window->getNormalClientSize(&size);

	PyObject *pyret = Py_BuildValue("(ii)", size.cx, size.cy);
	return pyret;
}

static PyObject *Window_getDisplayScaling(PyObject *self, PyObject *args)
{
	if (!PyArg_ParseTuple(args, ""))
		return NULL;

	if (!((Window_Object *)self)->p)
	{
		PyErr_SetString(PyExc_ValueError, "already destroyed.");
		return NULL;
	}

	Window *window = ((Window_Object *)self)->p;

	float scale = window->getDisplayScaling();

	PyObject *pyret = Py_BuildValue("f", scale);
	return pyret;
}

static PyObject *Window_getDisplayScalingFromPosition(PyObject *self, PyObject *args)
{
	int x;
	int y;

	if (!PyArg_ParseTuple(args, "ii", &x, &y))
		return NULL;

	float scale = Window::getDisplayScalingFromPosition(x, y);

	PyObject *pyret = Py_BuildValue("f", scale);
	return pyret;
}

static PyObject *Window_screenToClient(PyObject *self, PyObject *args)
{
	int x;
	int y;

	if (!PyArg_ParseTuple(args, "ii", &x, &y))
		return NULL;

	if (!((Window_Object *)self)->p)
	{
		PyErr_SetString(PyExc_ValueError, "already destroyed.");
		return NULL;
	}

	Window *window = ((Window_Object *)self)->p;

	POINT point;
	point.x = x;
	point.y = y;

	ScreenToClient(window->hwnd, &point);

	PyObject *pyret = Py_BuildValue("(ii)", point.x, point.y);
	return pyret;
}

static PyObject *Window_clientToScreen(PyObject *self, PyObject *args)
{
	int x;
	int y;

	if (!PyArg_ParseTuple(args, "ii", &x, &y))
		return NULL;

	if (!((Window_Object *)self)->p)
	{
		PyErr_SetString(PyExc_ValueError, "already destroyed.");
		return NULL;
	}

	Window *window = ((Window_Object *)self)->p;

	POINT point;
	point.x = x;
	point.y = y;

	ClientToScreen(window->hwnd, &point);

	PyObject *pyret = Py_BuildValue("(ii)", point.x, point.y);
	return pyret;
}

static PyObject *Window_setTimer(PyObject *self, PyObject *args)
{
	PyObject *func;
	int interval;

	if (!PyArg_ParseTuple(args, "Oi", &func, &interval))
		return NULL;

	if (!((Window_Object *)self)->p)
	{
		PyErr_SetString(PyExc_ValueError, "already destroyed.");
		return NULL;
	}

	Window *window = ((Window_Object *)self)->p;

	Py_XINCREF(func);
	window->timer_list.push_back(func);

	SetTimer(window->hwnd, (UINT_PTR)func, interval, NULL);

	Py_INCREF(Py_None);
	return Py_None;
}

static PyObject *Window_killTimer(PyObject *self, PyObject *args)
{
	PyObject *func;

	if (!PyArg_ParseTuple(args, "O", &func))
		return NULL;

	if (!((Window_Object *)self)->p)
	{
		PyErr_SetString(PyExc_ValueError, "already destroyed.");
		return NULL;
	}

	Window *window = ((Window_Object *)self)->p;
	Window::Reference reference(window);

	for (std::list<TimerInfo>::iterator i = window->timer_list.begin(); i != window->timer_list.end(); i++)
	{
		if ((i->pyobj) == NULL)
			continue;

		int equal = PyObject_RichCompareBool(func, i->pyobj, Py_EQ);
		if (equal < 0)
			return NULL;
		if (window->destroying)
			break;
		if (equal)
		{
			KillTimer(window->hwnd, (UINT_PTR)(i->pyobj));

			Py_CLEAR(i->pyobj);

			break;
		}
	}

	Py_INCREF(Py_None);
	return Py_None;
}

static PyObject *Window_delayedCall(PyObject *self, PyObject *args)
{
	PyObject *func;
	int timeout;

	if (!PyArg_ParseTuple(args, "Oi", &func, &timeout))
		return NULL;

	if (!((Window_Object *)self)->p)
	{
		PyErr_SetString(PyExc_ValueError, "already destroyed.");
		return NULL;
	}

	Window *window = ((Window_Object *)self)->p;

	Py_XINCREF(func);
	window->delayed_call_list.push_back(DelayedCallInfo(func, timeout));

	Py_INCREF(Py_None);
	return Py_None;
}

static PyObject *Window_setHotKey(PyObject *self, PyObject *args)
{
	int vk;
	int mod;
	PyObject *func;

	if (!PyArg_ParseTuple(args, "iiO", &vk, &mod, &func))
		return NULL;

	if (!((Window_Object *)self)->p)
	{
		PyErr_SetString(PyExc_ValueError, "already destroyed.");
		return NULL;
	}

	Window *window = ((Window_Object *)self)->p;

	// Find an unused ID in the range 0x0000 through 0xBFFF.
	int id;
	for (id = 0; id < 0xc000; ++id)
	{
		bool dup = false;
		for (std::list<HotKeyInfo>::const_iterator i = window->hotkey_list.begin(); i != window->hotkey_list.end(); ++i)
		{
			if (i->id == id)
			{
				dup = true;
				break;
			}
		}

		if (!dup)
		{
			break;
		}
	}

	if (id == 0xc000)
	{
		PyErr_SetString(PyExc_RuntimeError, "No hotkey IDs available.");
		return NULL;
	}

	try
	{
		window->hotkey_list.push_back(HotKeyInfo(func, id));
	}
	catch (const std::bad_alloc &)
	{
		return PyErr_NoMemory();
	}

	if (!RegisterHotKey(window->hwnd, id, mod, vk))
	{
		DWORD error = GetLastError();
		window->hotkey_list.pop_back();
		return PyErr_SetFromWindowsErr(error);
	}
	Py_INCREF(func);

	Py_INCREF(Py_None);
	return Py_None;
}

static PyObject *Window_killHotKey(PyObject *self, PyObject *args)
{
	PyObject *func;

	if (!PyArg_ParseTuple(args, "O", &func))
		return NULL;

	if (!((Window_Object *)self)->p)
	{
		PyErr_SetString(PyExc_ValueError, "already destroyed.");
		return NULL;
	}

	Window *window = ((Window_Object *)self)->p;
	Window::Reference reference(window);

	for (std::list<HotKeyInfo>::iterator i = window->hotkey_list.begin(); i != window->hotkey_list.end(); i++)
	{
		if (i->pyobj == NULL)
			continue;

		int equal = PyObject_RichCompareBool(func, i->pyobj, Py_EQ);
		if (equal < 0)
			return NULL;
		if (window->destroying)
			break;
		if (equal)
		{
			if (!UnregisterHotKey(window->hwnd, i->id))
				return PyErr_SetFromWindowsErr(0);

			PyObject *callback = i->pyobj;
			i->pyobj = NULL;
			if (window->hotkey_list_ref_count == 0)
				window->hotkey_list.erase(i);
			Py_DECREF(callback);

			break;
		}
	}

	Py_INCREF(Py_None);
	return Py_None;
}

static PyObject *Window_setTitle(PyObject *self, PyObject *args)
{
	PyObject *pystr;

	if (!PyArg_ParseTuple(args, "O", &pystr))
		return NULL;

	if (!((Window_Object *)self)->p)
	{
		PyErr_SetString(PyExc_ValueError, "already destroyed.");
		return NULL;
	}

	std::wstring str;
	if (!PythonUtil::PyStringToWideString(pystr, &str))
	{
		return NULL;
	}

	Window *window = ((Window_Object *)self)->p;

	::SetWindowText(window->hwnd, str.c_str());

	Py_INCREF(Py_None);
	return Py_None;
}

static PyObject *Window_setBGColor(PyObject *self, PyObject *args)
{
	int r, g, b;

	if (!PyArg_ParseTuple(args, "(iii)", &r, &g, &b))
		return NULL;

	if (!((Window_Object *)self)->p)
	{
		PyErr_SetString(PyExc_ValueError, "already destroyed.");
		return NULL;
	}

	Window *window = ((Window_Object *)self)->p;
	window->setBGColor(RGB(r, g, b));

	Py_INCREF(Py_None);
	return Py_None;
}

static PyObject *Window_setFrameColor(PyObject *self, PyObject *args)
{
	PyObject *pycolor;

	if (!PyArg_ParseTuple(args, "O", &pycolor))
		return NULL;

	if (!((Window_Object *)self)->p)
	{
		PyErr_SetString(PyExc_ValueError, "already destroyed.");
		return NULL;
	}

	Window *window = ((Window_Object *)self)->p;

	if (pycolor && PySequence_Check(pycolor))
	{
		int r, g, b;
		if (!PyArg_ParseTuple(pycolor, "iii", &r, &g, &b))
			return NULL;

		window->setFrameColor(RGB(r, g, b));
	}

	Py_INCREF(Py_None);
	return Py_None;
}

static PyObject *Window_setCaretColor(PyObject *self, PyObject *args)
{
	PyObject *pycolor0;
	PyObject *pycolor1;

	if (!PyArg_ParseTuple(args, "OO", &pycolor0, &pycolor1))
		return NULL;

	if (!((Window_Object *)self)->p)
	{
		PyErr_SetString(PyExc_ValueError, "already destroyed.");
		return NULL;
	}

	Window *window = ((Window_Object *)self)->p;

	if (pycolor0 && PySequence_Check(pycolor0) && pycolor1 && PySequence_Check(pycolor1))
	{
		int r0, g0, b0;
		if (!PyArg_ParseTuple(pycolor0, "iii", &r0, &g0, &b0))
			return NULL;

		int r1, g1, b1;
		if (!PyArg_ParseTuple(pycolor1, "iii", &r1, &g1, &b1))
			return NULL;

		window->setCaretColor(RGB(r0, g0, b0), RGB(r1, g1, b1));
	}

	Py_INCREF(Py_None);
	return Py_None;
}

static PyObject *Window_setMenu(PyObject *self, PyObject *args)
{
	PyObject *pymenu;

	if (!PyArg_ParseTuple(args, "O", &pymenu))
		return NULL;

	if (!((Window_Object *)self)->p)
	{
		PyErr_SetString(PyExc_ValueError, "already destroyed.");
		return NULL;
	}

	Window *window = ((Window_Object *)self)->p;

	if (MenuNode_Check(pymenu))
	{
		window->setMenu(pymenu);
	}
	else if (pymenu == Py_None)
	{
		window->setMenu(NULL);
	}
	else
	{
		PyErr_SetString(PyExc_TypeError, "invalid argument type.");
		return NULL;
	}

	Py_INCREF(Py_None);
	return Py_None;
}

static PyObject *Window_setCapture(PyObject *self, PyObject *args)
{
	if (!PyArg_ParseTuple(args, ""))
		return NULL;

	if (!((Window_Object *)self)->p)
	{
		PyErr_SetString(PyExc_ValueError, "already destroyed.");
		return NULL;
	}

	Window *window = ((Window_Object *)self)->p;

	window->setCapture();

	Py_INCREF(Py_None);
	return Py_None;
}

static PyObject *Window_releaseCapture(PyObject *self, PyObject *args)
{
	if (!PyArg_ParseTuple(args, ""))
		return NULL;

	if (!((Window_Object *)self)->p)
	{
		PyErr_SetString(PyExc_ValueError, "already destroyed.");
		return NULL;
	}

	Window *window = ((Window_Object *)self)->p;

	window->releaseCapture();

	Py_INCREF(Py_None);
	return Py_None;
}

static PyObject *Window_setMouseCursor(PyObject *self, PyObject *args)
{
	int id;

	if (!PyArg_ParseTuple(args, "i", &id))
		return NULL;

	if (!((Window_Object *)self)->p)
	{
		PyErr_SetString(PyExc_ValueError, "already destroyed.");
		return NULL;
	}

	Window *window = ((Window_Object *)self)->p;

	window->setMouseCursor(id);

	Py_INCREF(Py_None);
	return Py_None;
}

static PyObject *Window_drag(PyObject *self, PyObject *args)
{
	int x, y;

	if (!PyArg_ParseTuple(args, "ii", &x, &y))
		return NULL;

	if (!((Window_Object *)self)->p)
	{
		PyErr_SetString(PyExc_ValueError, "already destroyed.");
		return NULL;
	}

	Window *window = ((Window_Object *)self)->p;

	window->drag(x, y);

	Py_INCREF(Py_None);
	return Py_None;
}

static PyObject *Window_popupMenu(PyObject *self, PyObject *args, PyObject *kwds)
{
	int x;
	int y;
	PyObject *items;

	static char *kwlist[] = {
		"x",
		"y",
		"items",
		NULL};

	if (!PyArg_ParseTupleAndKeywords(args, kwds, "iiO", kwlist,
									 &x,
									 &y,
									 &items))
	{
		return NULL;
	}

	if (!((Window_Object *)self)->p)
	{
		PyErr_SetString(PyExc_ValueError, "already destroyed.");
		return NULL;
	}

	Window *window = ((Window_Object *)self)->p;
	Window::Reference reference(window);

	HMENU menu;
	menu = CreatePopupMenu();

	window->_clearPopupMenuCommands();

	if (!window->destroying && PySequence_Check(items))
	{
		int num_items = (int)PySequence_Length(items);
		for (int i = 0; !window->destroying && i < num_items; ++i)
		{
			PyObject *item = PySequence_GetItem(items, i);

			PyObject *pyname;
			PyObject *func;
			PyObject *pyoption = NULL;
			if (!PyArg_ParseTuple(item, "OO|O", &pyname, &func, &pyoption))
			{
				Py_XDECREF(item);
				DestroyMenu(menu);
				return NULL;
			}

			std::wstring name;
			if (!PythonUtil::PyStringToWideString(pyname, &name))
			{
				Py_XDECREF(item);
				DestroyMenu(menu);
				return NULL;
			}

			if (name == L"-")
			{
				AppendMenu(menu, MF_SEPARATOR, 0, L"");
			}
			else
			{
				if (ID_POPUP_MENUITEM + window->popup_menu_commands.size() > ID_POPUP_MENUITEM_MAX)
				{
					Py_XDECREF(item);
					DestroyMenu(menu);
					PyErr_SetString(PyExc_ValueError, "too many menu items.");
					return NULL;
				}

				if (pyoption)
				{
					if (pyoption == Py_True || pyoption == Py_False)
					{
						AppendMenu(menu, MF_ENABLED | ((pyoption == Py_True) ? MF_CHECKED : MF_UNCHECKED), ID_POPUP_MENUITEM + window->popup_menu_commands.size(), name.c_str());
					}
					else
					{
						Py_XDECREF(item);
						DestroyMenu(menu);
						PyErr_SetString(PyExc_TypeError, "invalid menu option type.");
						return NULL;
					}
				}
				else
				{
					AppendMenu(menu, MF_ENABLED, ID_POPUP_MENUITEM + window->popup_menu_commands.size(), name.c_str());
				}

				window->popup_menu_commands.push_back(func);
				Py_INCREF(func);
			}

			Py_XDECREF(item);
		}
	}

	if (!window->destroying)
	{
		HWND hwnd = window->hwnd;

		SetForegroundWindow(hwnd); // Bring the window to the foreground.
		if (!window->destroying)
			SetFocus(hwnd); // Set focus so the menu can be dismissed.

		if (!window->destroying)
			TrackPopupMenu(menu, TPM_TOPALIGN | TPM_LEFTALIGN | TPM_RIGHTBUTTON, x, y, 0, hwnd, 0);

		if (!window->destroying)
			PostMessage(hwnd, WM_NULL, 0, 0); // Prevent the next popup menu from closing immediately.
	}

	DestroyMenu(menu);

	Py_INCREF(Py_None);
	return Py_None;
}

static PyObject *Window_enumFonts(PyObject *self, PyObject *args)
{
	if (!PyArg_ParseTuple(args, ""))
		return NULL;

	std::vector<std::wstring> font_list;
	Window::enumFonts(&font_list);

	std::sort(font_list.begin(), font_list.end());

	PyObject *pyret = PyList_New(0);
	for (std::vector<std::wstring>::const_iterator i = font_list.begin(); i != font_list.end(); i++)
	{
		PyObject *data = Py_BuildValue("u", (*i).c_str());

		PyList_Append(pyret, data);

		Py_XDECREF(data);
	}
	return pyret;
}

static PyObject *Window_sendIpc(PyObject *self, PyObject *args)
{
	PyObject *pyhwnd;
	char *buf;
	Py_ssize_t bufsize;

	if (!PyArg_ParseTuple(args, "Os#", &pyhwnd, &buf, &bufsize))
		return NULL;

	size_t hwnd_value = PyLong_AsSize_t(pyhwnd);
	if (PyErr_Occurred())
		return NULL;
	HWND hwnd = reinterpret_cast<HWND>(hwnd_value);
	if ((size_t)bufsize > MAXDWORD)
	{
		PyErr_SetString(PyExc_OverflowError, "IPC data is too large.");
		return NULL;
	}

	COPYDATASTRUCT data;
	data.dwData = 0x101;
	data.cbData = (DWORD)bufsize;
	data.lpData = buf;
	SendMessage(hwnd, WM_COPYDATA, (WPARAM)NULL, (LPARAM)&data);

	Py_INCREF(Py_None);
	return Py_None;
}

static PyMethodDef Window_methods[] = {
	{"getHWND", Window_getHWND, METH_VARARGS, ""},
	{"getHINSTANCE", Window_getHINSTANCE, METH_VARARGS, ""},
	{"show", Window_show, METH_VARARGS, ""},
	{"enable", Window_enable, METH_VARARGS, ""},
	{"destroy", Window_destroy, METH_VARARGS, ""},
	{"activate", Window_activate, METH_VARARGS, ""},
	{"inactivate", Window_inactivate, METH_VARARGS, ""},
	{"foreground", Window_foreground, METH_VARARGS, ""},
	{"restore", Window_restore, METH_VARARGS, ""},
	{"maximize", Window_maximize, METH_VARARGS, ""},
	{"minimize", Window_minimize, METH_VARARGS, ""},
	{"topmost", Window_topmost, METH_VARARGS, ""},
	{"isEnabled", Window_isEnabled, METH_VARARGS, ""},
	{"isVisible", Window_isVisible, METH_VARARGS, ""},
	{"isMaximized", Window_isMaximized, METH_VARARGS, ""},
	{"isMinimized", Window_isMinimized, METH_VARARGS, ""},
	{"isActive", Window_isActive, METH_VARARGS, ""},
	{"isForeground", Window_isForeground, METH_VARARGS, ""},
	{"clear", Window_clear, METH_VARARGS, ""},
	{"flushPaint", Window_flushPaint, METH_VARARGS, ""},
	{"bitBlt", Window_bitBlt, METH_VARARGS, ""},
	{"messageLoop", (PyCFunction)Window_messageLoop, METH_VARARGS | METH_KEYWORDS, ""},
	{"removeKeyMessage", Window_removeKeyMessage, METH_VARARGS, ""},
	{"quit", Window_quit, METH_VARARGS, ""},
	{"getWindowRect", Window_getWindowRect, METH_VARARGS, ""},
	{"getClientSize", Window_getClientSize, METH_VARARGS, ""},
	{"getNormalWindowRect", Window_getNormalWindowRect, METH_VARARGS, ""},
	{"getNormalClientSize", Window_getNormalClientSize, METH_VARARGS, ""},
	{"getDisplayScaling", Window_getDisplayScaling, METH_VARARGS, ""},
	{"getDisplayScalingFromPosition", Window_getDisplayScalingFromPosition, METH_STATIC | METH_VARARGS, ""},
	{"screenToClient", Window_screenToClient, METH_VARARGS, ""},
	{"clientToScreen", Window_clientToScreen, METH_VARARGS, ""},
	{"setTimer", Window_setTimer, METH_VARARGS, ""},
	{"killTimer", Window_killTimer, METH_VARARGS, ""},
	{"delayedCall", Window_delayedCall, METH_VARARGS, ""},
	{"setHotKey", Window_setHotKey, METH_VARARGS, ""},
	{"killHotKey", Window_killHotKey, METH_VARARGS, ""},
	{"setImeRect", Window_setImeRect, METH_VARARGS, ""},
	{"enableIme", Window_enableIme, METH_VARARGS, ""},
	{"setPositionAndSize", (PyCFunction)Window_setPositionAndSize, METH_VARARGS | METH_KEYWORDS, ""},
	{"setTitle", (PyCFunction)Window_setTitle, METH_VARARGS, ""},
	{"setBGColor", (PyCFunction)Window_setBGColor, METH_VARARGS, ""},
	{"setFrameColor", (PyCFunction)Window_setFrameColor, METH_VARARGS, ""},
	{"setCaretColor", (PyCFunction)Window_setCaretColor, METH_VARARGS, ""},
	{"setMenu", (PyCFunction)Window_setMenu, METH_VARARGS, ""},
	{"setCapture", (PyCFunction)Window_setCapture, METH_VARARGS, ""},
	{"releaseCapture", (PyCFunction)Window_releaseCapture, METH_VARARGS, ""},
	{"setMouseCursor", (PyCFunction)Window_setMouseCursor, METH_VARARGS, ""},
	{"drag", (PyCFunction)Window_drag, METH_VARARGS, ""},
	{"popupMenu", (PyCFunction)Window_popupMenu, METH_VARARGS | METH_KEYWORDS, ""},
	{"enumFonts", (PyCFunction)Window_enumFonts, METH_STATIC | METH_VARARGS, ""},
	{"sendIpc", (PyCFunction)Window_sendIpc, METH_STATIC | METH_VARARGS, ""},
	{NULL, NULL}};

PyTypeObject Window_Type = {
	PyVarObject_HEAD_INIT(NULL, 0) "Window",  /* tp_name */
	sizeof(Window_Object),					  /* tp_basicsize */
	0,										  /* tp_itemsize */
	(destructor)Window_dealloc,				  /* tp_dealloc */
	0,										  /* tp_print */
	0,										  /* tp_getattr */
	0,										  /* tp_setattr */
	0,										  /* tp_reserved */
	0,										  /* tp_repr */
	0,										  /* tp_as_number */
	0,										  /* tp_as_sequence */
	0,										  /* tp_as_mapping */
	0,										  /* tp_hash */
	0,										  /* tp_call */
	0,										  /* tp_str */
	PyObject_GenericGetAttr,				  /* tp_getattro */
	PyObject_GenericSetAttr,				  /* tp_setattro */
	0,										  /* tp_as_buffer */
	Py_TPFLAGS_DEFAULT | Py_TPFLAGS_BASETYPE, /* tp_flags */
	"",										  /* tp_doc */
	0,										  /* tp_traverse */
	0,										  /* tp_clear */
	0,										  /* tp_richcompare */
	0,										  /* tp_weaklistoffset */
	0,										  /* tp_iter */
	0,										  /* tp_iternext */
	Window_methods,							  /* tp_methods */
	0,										  /* tp_members */
	0,										  /* tp_getset */
	0,										  /* tp_base */
	0,										  /* tp_dict */
	0,										  /* tp_descr_get */
	0,										  /* tp_descr_set */
	0,										  /* tp_dictoffset */
	Window_init,							  /* tp_init */
	0,										  /* tp_alloc */
	PyType_GenericNew,						  /* tp_new */
	0,										  /* tp_free */
};

// ----------------------------------------------------------------------------
//
// ----------------------------------------------------------------------------

static int TaskTrayIcon_init(PyObject *self, PyObject *args, PyObject *kwds)
{
	if (((TaskTrayIcon_Object *)self)->p)
	{
		PyErr_SetString(PyExc_ValueError, "already initialized.");
		return -1;
	}
	PyObject *pystr_title = NULL;
	PyObject *lbuttondown_handler = NULL;
	PyObject *lbuttonup_handler = NULL;
	PyObject *rbuttondown_handler = NULL;
	PyObject *rbuttonup_handler = NULL;
	PyObject *lbuttondoubleclick_handler = NULL;

	static char *kwlist[] = {
		"title",
		"lbuttondown_handler",
		"lbuttonup_handler",
		"rbuttondown_handler",
		"rbuttonup_handler",
		"lbuttondoubleclick_handler",
		NULL};

	if (!PyArg_ParseTupleAndKeywords(args, kwds, "|OOOOOO", kwlist,
									 &pystr_title,
									 &lbuttondown_handler,
									 &lbuttonup_handler,
									 &rbuttondown_handler,
									 &rbuttonup_handler,
									 &lbuttondoubleclick_handler))
	{
		return -1;
	}

	std::wstring str_title;
	if (pystr_title)
	{
		if (!PythonUtil::PyStringToWideString(pystr_title, &str_title))
		{
			return -1;
		}
	}

	if (str_title.size() >= sizeof(NOTIFYICONDATA::szTip) / sizeof(wchar_t))
	{
		PyErr_SetString(PyExc_ValueError, "title must be at most 127 UTF-16 code units.");
		return -1;
	}

	TaskTrayIcon::Param param;
	param.title = str_title;
	param.lbuttondown_handler = lbuttondown_handler;
	param.lbuttonup_handler = lbuttonup_handler;
	param.rbuttondown_handler = rbuttondown_handler;
	param.rbuttonup_handler = rbuttonup_handler;
	param.lbuttondoubleclick_handler = lbuttondoubleclick_handler;

	TaskTrayIcon *task_tray_icon;
	try
	{
		task_tray_icon = new TaskTrayIcon(param);
	}
	catch (const std::bad_alloc &)
	{
		PyErr_NoMemory();
		return -1;
	}
	if (PyErr_Occurred() || !task_tray_icon->hwnd)
	{
		if (!PyErr_Occurred())
			PyErr_SetString(PyExc_ValueError, "destroyed during initialization.");
		PyObject *error = PyErr_GetRaisedException();
		if (task_tray_icon->hwnd)
			task_tray_icon->destroy();
		delete task_tray_icon;
		PyErr_SetRaisedException(error);
		return -1;
	}
	task_tray_icon->creating = false;

	task_tray_icon->SetPyObject(self);

	((TaskTrayIcon_Object *)self)->p = task_tray_icon;

	return 0;
}

static void TaskTrayIcon_dealloc(PyObject *self)
{
	TaskTrayIcon *task_tray_icon = ((TaskTrayIcon_Object *)self)->p;
	if (task_tray_icon)
	{
		task_tray_icon->SetPyObject(NULL);
	}

	self->ob_type->tp_free(self);
}

static PyObject *TaskTrayIcon_destroy(PyObject *self, PyObject *args)
{
	if (!PyArg_ParseTuple(args, ""))
		return NULL;

	if (!((TaskTrayIcon_Object *)self)->p)
	{
		PyErr_SetString(PyExc_ValueError, "already destroyed.");
		return NULL;
	}

	TaskTrayIcon *task_tray_icon = ((TaskTrayIcon_Object *)self)->p;

	task_tray_icon->destroy();

	Py_INCREF(Py_None);
	return Py_None;
}

static PyObject *TaskTrayIcon_popupMenu(PyObject *self, PyObject *args, PyObject *kwds)
{
	TaskTrayIcon *task_tray_icon = ((TaskTrayIcon_Object *)self)->p;
	if (!task_tray_icon)
	{
		PyErr_SetString(PyExc_ValueError, "already destroyed.");
		return NULL;
	}
	if (task_tray_icon->popup_menu_active)
	{
		PyErr_SetString(PyExc_ValueError, "popupMenu is already active.");
		return NULL;
	}
	TaskTrayIcon::Reference reference(task_tray_icon);
	// Argument conversion and command finalizers can call back into this menu.
	struct PopupScope
	{
		TaskTrayIcon *icon;
		PopupScope(TaskTrayIcon *icon) : icon(icon) { icon->popup_menu_active = true; }
		~PopupScope() { icon->popup_menu_active = false; }
	} popup_scope(task_tray_icon);

	int x;
	int y;
	PyObject *items;

	static char *kwlist[] = {
		"x",
		"y",
		"items",
		NULL};

	if (!PyArg_ParseTupleAndKeywords(args, kwds, "iiO", kwlist,
									 &x,
									 &y,
									 &items))
	{
		return NULL;
	}

	if (!task_tray_icon->hwnd)
	{
		PyErr_SetString(PyExc_ValueError, "already destroyed.");
		return NULL;
	}

	auto alive = [&]() {
		if (task_tray_icon->hwnd)
			return true;
		PyErr_SetString(PyExc_ValueError, "already destroyed.");
		return false;
	};

	HMENU menu;
	menu = CreatePopupMenu();
	if (!menu)
		return PyErr_SetFromWindowsErr(0);

	task_tray_icon->_clearPopupMenuCommands();
	if (!alive())
	{
		DestroyMenu(menu);
		return NULL;
	}

	if (PySequence_Check(items))
	{
		Py_ssize_t num_items = PySequence_Length(items);
		if (num_items < 0 || !alive())
		{
			DestroyMenu(menu);
			return NULL;
		}
		for (Py_ssize_t i = 0; i < num_items; ++i)
		{
			PyObject *item = PySequence_GetItem(items, i);
			if (!item || !alive())
			{
				Py_XDECREF(item);
				DestroyMenu(menu);
				return NULL;
			}

			PyObject *pyname;
			PyObject *func;
			PyObject *pyoption = NULL;
			if (!PyArg_ParseTuple(item, "OO|O", &pyname, &func, &pyoption))
			{
				Py_XDECREF(item);
				DestroyMenu(menu);
				return NULL;
			}

			std::wstring name;
			if (!PythonUtil::PyStringToWideString(pyname, &name))
			{
				Py_XDECREF(item);
				DestroyMenu(menu);
				return NULL;
			}

			if (name == L"-")
			{
				AppendMenu(menu, MF_SEPARATOR, 0, L"");
			}
			else
			{
				if (ID_POPUP_MENUITEM + task_tray_icon->popup_menu_commands.size() > ID_POPUP_MENUITEM_MAX)
				{
					Py_XDECREF(item);
					DestroyMenu(menu);
					PyErr_SetString(PyExc_ValueError, "too many menu items.");
					return NULL;
				}

				if (pyoption)
				{
					if (pyoption == Py_True || pyoption == Py_False)
					{
						AppendMenu(menu, MF_ENABLED | ((pyoption == Py_True) ? MF_CHECKED : MF_UNCHECKED), ID_POPUP_MENUITEM + task_tray_icon->popup_menu_commands.size(), name.c_str());
					}
					else
					{
						Py_XDECREF(item);
						DestroyMenu(menu);
						PyErr_SetString(PyExc_TypeError, "invalid menu option type.");
						return NULL;
					}
				}
				else
				{
					AppendMenu(menu, MF_ENABLED, ID_POPUP_MENUITEM + task_tray_icon->popup_menu_commands.size(), name.c_str());
				}

				try
				{
					task_tray_icon->popup_menu_commands.push_back(func);
				}
				catch (const std::bad_alloc &)
				{
					Py_DECREF(item);
					DestroyMenu(menu);
					return PyErr_NoMemory();
				}
				Py_INCREF(func);
			}

			Py_XDECREF(item);
			if (!alive())
			{
				DestroyMenu(menu);
				return NULL;
			}
		}
	}

	{
		HWND hwnd = task_tray_icon->hwnd;

		SetForegroundWindow(hwnd); // Bring the window to the foreground.
		if (!alive())
		{
			DestroyMenu(menu);
			return NULL;
		}
		SetFocus(hwnd);			   // Set focus so the menu can be dismissed.

		if (!alive())
		{
			DestroyMenu(menu);
			return NULL;
		}
		TrackPopupMenu(menu, TPM_TOPALIGN | TPM_LEFTALIGN | TPM_RIGHTBUTTON, x, y, 0, hwnd, 0);

		if (task_tray_icon->hwnd)
			PostMessage(hwnd, WM_NULL, 0, 0); // Prevent the next popup menu from closing immediately.
	}

	DestroyMenu(menu);

	Py_INCREF(Py_None);
	return Py_None;
}

static PyMethodDef TaskTrayIcon_methods[] = {
	{"destroy", TaskTrayIcon_destroy, METH_VARARGS, ""},
	{"popupMenu", (PyCFunction)TaskTrayIcon_popupMenu, METH_VARARGS | METH_KEYWORDS, ""},
	{NULL, NULL}};

PyTypeObject TaskTrayIcon_Type = {
	PyVarObject_HEAD_INIT(NULL, 0) "TaskTrayIcon", /* tp_name */
	sizeof(TaskTrayIcon_Object),				   /* tp_basicsize */
	0,											   /* tp_itemsize */
	(destructor)TaskTrayIcon_dealloc,			   /* tp_dealloc */
	0,											   /* tp_print */
	0,											   /* tp_getattr */
	0,											   /* tp_setattr */
	0,											   /* tp_reserved */
	0,											   /* tp_repr */
	0,											   /* tp_as_number */
	0,											   /* tp_as_sequence */
	0,											   /* tp_as_mapping */
	0,											   /* tp_hash */
	0,											   /* tp_call */
	0,											   /* tp_str */
	PyObject_GenericGetAttr,					   /* tp_getattro */
	PyObject_GenericSetAttr,					   /* tp_setattro */
	0,											   /* tp_as_buffer */
	Py_TPFLAGS_DEFAULT | Py_TPFLAGS_BASETYPE,	   /* tp_flags */
	"",											   /* tp_doc */
	0,											   /* tp_traverse */
	0,											   /* tp_clear */
	0,											   /* tp_richcompare */
	0,											   /* tp_weaklistoffset */
	0,											   /* tp_iter */
	0,											   /* tp_iternext */
	TaskTrayIcon_methods,						   /* tp_methods */
	0,											   /* tp_members */
	0,											   /* tp_getset */
	0,											   /* tp_base */
	0,											   /* tp_dict */
	0,											   /* tp_descr_get */
	0,											   /* tp_descr_set */
	0,											   /* tp_dictoffset */
	TaskTrayIcon_init,							   /* tp_init */
	0,											   /* tp_alloc */
	PyType_GenericNew,							   /* tp_new */
	0,											   /* tp_free */
};

// ----------------------------------------------------------------------------
//
// ----------------------------------------------------------------------------

enum
{
	Line_End_CR = 1 << 0,
	Line_End_LF = 1 << 1,
	Line_End_CRLF = Line_End_CR | Line_End_LF,

	Line_BG_1 = 1 << 2,
	Line_BG_2 = 1 << 3,
	Line_BG_3 = Line_BG_1 | Line_BG_2,

	Line_Modified = 1 << 4,

	Line_Bookmark_1 = 1 << 5,
	Line_Bookmark_2 = 1 << 6,
	Line_Bookmark_3 = 1 << 7,
};

enum
{
	Line_End_Bit = 0,
	Line_BG_Bit = 2,
	Line_Modified_Bit = 4,
	Line_Bookmark_Bit = 5,
};

static PyObject *line_cr = NULL;
static PyObject *line_lf = NULL;
static PyObject *line_crlf = NULL;
static PyObject *line_empty = NULL;

static void Line_static_init()
{
	line_cr = Py_BuildValue("u", L"\r");
	line_lf = Py_BuildValue("u", L"\n");
	line_crlf = Py_BuildValue("u", L"\r\n");
	line_empty = Py_BuildValue("u", L"");
}

static void Line_static_term()
{
	Py_DECREF(line_cr);
	Py_DECREF(line_lf);
	Py_DECREF(line_crlf);
	Py_DECREF(line_empty);
}

static int _Line_CheckLineEnd(const wchar_t *s, Py_ssize_t len)
{
	if (len >= 2 && s[len - 2] == '\r' && s[len - 1] == '\n')
	{
		return Line_End_CRLF;
	}
	else if (len >= 1 && s[len - 1] == '\n')
	{
		return Line_End_LF;
	}
	else if (len >= 1 && s[len - 1] == '\r')
	{
		return Line_End_CR;
	}
	return 0;
}

static int Line_init(PyObject *self, PyObject *args, PyObject *kwds)
{
	PyObject *text;

	static char *kwlist[] = {
		"s",
		NULL};

	if (!PyArg_ParseTupleAndKeywords(args, kwds, "U", kwlist, &text))
	{
		return -1;
	}

	Py_ssize_t len;
	wchar_t *s = PyUnicode_AsWideCharString(text, &len);
	if (!s)
		return -1;

	int lineend = _Line_CheckLineEnd(s, len);
	switch (lineend)
	{
	case Line_End_CR:
	case Line_End_LF:
		len -= 1;
		break;

	case Line_End_CRLF:
		len -= 2;
		break;
	}

	PyObject *body = PyUnicode_FromWideChar(s, len);
	PyMem_Free(s);
	if (!body)
		return -1;

	Py_XSETREF(((Line_Object *)self)->s, body);
	Py_CLEAR(((Line_Object *)self)->ctx);
	Py_CLEAR(((Line_Object *)self)->tokens);
	((Line_Object *)self)->flags = lineend;

	return 0;
}

static void Line_dealloc(PyObject *self)
{
	Py_XDECREF(((Line_Object *)self)->s);
	Py_XDECREF(((Line_Object *)self)->ctx);
	Py_XDECREF(((Line_Object *)self)->tokens);

	self->ob_type->tp_free(self);
}

static PyObject *Line_GetAttrString(PyObject *self, const char *attr_name)
{
	switch (attr_name[0])
	{
	case 's':
		if (strcmp(attr_name, "s") == 0)
		{
			PyObject *value = ((Line_Object *)self)->s;

			if (!value)
			{
				value = Py_None;
			}

			Py_INCREF(value);
			return value;
		}
		break;

	case 'e':
		if (strcmp(attr_name, "end") == 0)
		{
			int lineend = ((Line_Object *)self)->flags & (Line_End_CR | Line_End_LF);

			switch (lineend)
			{
			case Line_End_CR:
				Py_INCREF(line_cr);
				return line_cr;

			case Line_End_LF:
				Py_INCREF(line_lf);
				return line_lf;

			case Line_End_CRLF:
				Py_INCREF(line_crlf);
				return line_crlf;
			}

			Py_INCREF(line_empty);
			return line_empty;
		}
		break;

	case 'c':
		if (strcmp(attr_name, "ctx") == 0)
		{
			PyObject *value = ((Line_Object *)self)->ctx;
			if (!value)
			{
				value = Py_None;
			}
			Py_INCREF(value);
			return value;
		}
		break;

	case 't':
		if (strcmp(attr_name, "tokens") == 0)
		{
			PyObject *value = ((Line_Object *)self)->tokens;
			if (!value)
			{
				value = Py_None;
			}
			Py_INCREF(value);
			return value;
		}
		break;

	case 'b':
		if (strcmp(attr_name, "bg") == 0)
		{
			int bg = (((Line_Object *)self)->flags & (Line_BG_1 | Line_BG_2)) >> Line_BG_Bit;
			return Py_BuildValue("i", bg);
		}
		else if (strcmp(attr_name, "bookmark") == 0)
		{
			int bookmark = (((Line_Object *)self)->flags & (Line_Bookmark_1 | Line_Bookmark_2 | Line_Bookmark_3)) >> Line_Bookmark_Bit;
			return Py_BuildValue("i", bookmark);
		}
		break;

	case 'm':
		if (strcmp(attr_name, "modified") == 0)
		{
			if (((Line_Object *)self)->flags & Line_Modified)
			{
				Py_INCREF(Py_True);
				return Py_True;
			}
			else
			{
				Py_INCREF(Py_False);
				return Py_False;
			}
		}
		break;
	}

	PyErr_SetString(PyExc_AttributeError, attr_name);
	return NULL;
}

static int Line_SetAttrString(PyObject *self, const char *attr_name, PyObject *value)
{
	switch (attr_name[0])
	{
	case 's':
		if (strcmp(attr_name, "s") == 0)
		{
			Py_XDECREF(((Line_Object *)self)->s);
			((Line_Object *)self)->s = value;
			Py_XINCREF(((Line_Object *)self)->s);
			return 0;
		}
		break;

	case 'e':
		if (strcmp(attr_name, "end") == 0)
		{
			if (PyUnicode_Check(value))
			{
				Py_ssize_t len;
				wchar_t *s = PyUnicode_AsWideCharString(value, &len);
				if (!s)
					return -1;
				int lineend = _Line_CheckLineEnd(s, len);
				PyMem_Free(s);

				((Line_Object *)self)->flags &= ~(Line_End_CR | Line_End_LF);
				((Line_Object *)self)->flags |= lineend;

				return 0;
			}
			else
			{
				PyErr_SetString(PyExc_TypeError, "'end' must be a unicode object.");
				return -1;
			}
		}
		break;

	case 'c':
		if (strcmp(attr_name, "ctx") == 0)
		{
			Py_XDECREF(((Line_Object *)self)->ctx);
			((Line_Object *)self)->ctx = value;
			Py_XINCREF(((Line_Object *)self)->ctx);
			return 0;
		}
		break;

	case 't':
		if (strcmp(attr_name, "tokens") == 0)
		{
			Py_XDECREF(((Line_Object *)self)->tokens);
			((Line_Object *)self)->tokens = value;
			Py_XINCREF(((Line_Object *)self)->tokens);
			return 0;
		}
		break;

	case 'b':
		if (strcmp(attr_name, "bg") == 0)
		{
			if (!PyLong_Check(value))
			{
				PyErr_SetString(PyExc_TypeError, "'bg' must be a int object.");
				return -1;
			}

			long bg = PyLong_AsLong(value);
			if (bg == -1 && PyErr_Occurred())
				return -1;
			if (bg < 0 || bg > 3)
			{
				PyErr_SetString(PyExc_ValueError, "'bg' must be between 0 and 3.");
				return -1;
			}

			((Line_Object *)self)->flags &= ~(Line_BG_1 | Line_BG_2);
			((Line_Object *)self)->flags |= bg << Line_BG_Bit;

			return 0;
		}
		else if (strcmp(attr_name, "bookmark") == 0)
		{
			if (!PyLong_Check(value))
			{
				PyErr_SetString(PyExc_TypeError, "'bookmark' must be a int object.");
				return -1;
			}

			long bookmark = PyLong_AsLong(value);
			if (bookmark == -1 && PyErr_Occurred())
				return -1;
			if (bookmark < 0 || bookmark > 7)
			{
				PyErr_SetString(PyExc_ValueError, "'bookmark' must be between 0 and 7.");
				return -1;
			}

			((Line_Object *)self)->flags &= ~(Line_Bookmark_1 | Line_Bookmark_2 | Line_Bookmark_3);
			((Line_Object *)self)->flags |= bookmark << Line_Bookmark_Bit;

			return 0;
		}
		break;

	case 'm':
		if (strcmp(attr_name, "modified") == 0)
		{
			int modified;
			if (value == Py_True)
			{
				modified = Line_Modified;
			}
			else if (value == Py_False)
			{
				modified = 0;
			}
			else
			{
				PyErr_SetString(PyExc_TypeError, "'modified' must be True or False.");
				return -1;
			}

			((Line_Object *)self)->flags &= ~(Line_Modified);
			((Line_Object *)self)->flags |= modified;

			return 0;
		}
		break;
	}

	PyErr_SetString(PyExc_AttributeError, attr_name);
	return -1;
}

static PyMethodDef Line_methods[] = {
	{NULL, NULL}};

PyTypeObject Line_Type = {
	PyVarObject_HEAD_INIT(NULL, 0) "Line",	  /* tp_name */
	sizeof(Line_Object),					  /* tp_basicsize */
	0,										  /* tp_itemsize */
	(destructor)Line_dealloc,				  /* tp_dealloc */
	0,										  /* tp_print */
	(getattrfunc)Line_GetAttrString,		  /* tp_getattr */
	(setattrfunc)Line_SetAttrString,		  /* tp_setattr */
	0,										  /* tp_reserved */
	0,										  /* tp_repr */
	0,										  /* tp_as_number */
	0,										  /* tp_as_sequence */
	0,										  /* tp_as_mapping */
	0,										  /* tp_hash */
	0,										  /* tp_call */
	0,										  /* tp_str */
	0,										  /* tp_getattro */
	0,										  /* tp_setattro */
	0,										  /* tp_as_buffer */
	Py_TPFLAGS_DEFAULT | Py_TPFLAGS_BASETYPE, /* tp_flags */
	"",										  /* tp_doc */
	0,										  /* tp_traverse */
	0,										  /* tp_clear */
	0,										  /* tp_richcompare */
	0,										  /* tp_weaklistoffset */
	0,										  /* tp_iter */
	0,										  /* tp_iternext */
	Line_methods,							  /* tp_methods */
	0,										  /* tp_members */
	0,										  /* tp_getset */
	0,										  /* tp_base */
	0,										  /* tp_dict */
	0,										  /* tp_descr_get */
	0,										  /* tp_descr_set */
	0,										  /* tp_dictoffset */
	Line_init,								  /* tp_init */
	0,										  /* tp_alloc */
	PyType_GenericNew,						  /* tp_new */
	0,										  /* tp_free */
};

// ----------------------------------------------------------------------------
//
// ----------------------------------------------------------------------------

static PyObject *_registerWindowClass(PyObject *self, PyObject *args)
{
	PyObject *pyprefix;

	if (!PyArg_ParseTuple(args, "O", &pyprefix))
		return NULL;

	std::wstring prefix;
	if (pyprefix)
	{
		if (!PythonUtil::PyStringToWideString(pyprefix, &prefix))
		{
			return NULL;
		}
	}

	WINDOW_CLASS_NAME = prefix + L"WindowClass";
	TASKTRAY_WINDOW_CLASS_NAME = prefix + L"TaskTrayWindowClass";

	if (!Window::_registerWindowClass())
	{
		PyErr_SetFromWindowsErr(0);
		return NULL;
	}

	if (!TaskTrayIcon::_registerWindowClass())
	{
		PyErr_SetFromWindowsErr(0);
		return NULL;
	}

	Py_INCREF(Py_None);
	return Py_None;
}

static PyObject *_registerCommandInfoConstructor(PyObject *self, PyObject *args)
{
	PyObject *_command_info_constructor;

	if (!PyArg_ParseTuple(args, "O", &_command_info_constructor))
		return NULL;

	Py_XDECREF(command_info_constructor);
	command_info_constructor = _command_info_constructor;
	Py_INCREF(command_info_constructor);

	Py_INCREF(Py_None);
	return Py_None;
}

static int _blockDetectorCallback(PyObject *py_report_func, PyFrameObject *frame, int what, PyObject *arg)
{
	static DWORD tick_prev = GetTickCount();
	DWORD tick = GetTickCount();
	DWORD delta = tick - tick_prev;
	tick_prev = tick;

	if (delta > 1000)
	{
		PyObject *pyarglist = Py_BuildValue("()");
		PyObject *pyresult = PyObject_Call(py_report_func, pyarglist, NULL);
		Py_DECREF(pyarglist);
		if (pyresult)
		{
			Py_DECREF(pyresult);
		}
		else
		{
			PyErr_Print();
		}
	}

	return 0;
}

static PyObject *py_report_func;

static PyObject *_enableBlockDetector(PyObject *self, PyObject *args)
{
	PyObject *_py_report_func;

	if (!PyArg_ParseTuple(args, "O", &_py_report_func))
		return NULL;

	Py_XDECREF(py_report_func);
	py_report_func = _py_report_func;
	Py_INCREF(py_report_func);

	Py_INCREF(Py_None);
	return Py_None;
}

static PyObject *_setBlockDetector(PyObject *self, PyObject *args)
{
	if (!PyArg_ParseTuple(args, ""))
		return NULL;

	if (py_report_func)
	{
		PyEval_SetProfile(_blockDetectorCallback, py_report_func);
	}

	Py_INCREF(Py_None);
	return Py_None;
}

/**
@cond japanese
@page ckit_native ckitネイティブAPI

import ckitで使うネイティブ部品です。通常の文字窓は@ref widget のTextWindow、
複数行編集は@ref textwidget を先に利用できます。ここではそれらの土台と低水準描画を説明します。
表はselfを省き、インスタンス操作にも型名を付けます（実際はplane.setFont(font)等）。
特記しない整数はC int、色は0～255の3整数tuple、座標/寸法はピクセルです。文字列はstrでNULを含めません（Lineと長さ付きsendIpcは除く）。埋め込みNULはValueErrorです。
位置引数が基本で、キーワードを受ける操作は明記します。引数解析の失敗はTypeError/OverflowErrorです。
ネイティブ部品を受ける場所へNoneや異なる型を渡さないでください。全境界で型を検査する実装ではありません。
Window/Plane/TaskTrayIconとそのコールバックは作成したUIスレッドで操作し、ワーカーからの操作はSyncCall等でUIへ戻します。
完成例は@ref extensions を参照してください。

このページで使うckit定数は次の値です。ORIGINの横/縦は各1種類を選んでORします。
LINE_DOTは辺のフラグへ追加します。

| 定数 | 値 |
|---|---|
| ORIGIN_X_LEFT, ORIGIN_X_CENTER, ORIGIN_X_RIGHT | 0, 1, 2 |
| ORIGIN_Y_TOP, ORIGIN_Y_CENTER, ORIGIN_Y_BOTTOM | 0, 4, 8 |
| MODKEY_ALT, MODKEY_CTRL, MODKEY_SHIFT, MODKEY_WIN | 1, 2, 4, 8 |
| LINE_LEFT, LINE_RIGHT, LINE_TOP, LINE_BOTTOM, LINE_DOT, LINE_RECTANGLE | 1, 2, 4, 8, 16, 15 |
| MOUSE_CURSOR_APPSTARTING, MOUSE_CURSOR_ARROW, MOUSE_CURSOR_CROSS, MOUSE_CURSOR_HAND, MOUSE_CURSOR_HELP, MOUSE_CURSOR_IBEAM, MOUSE_CURSOR_NO | 1～7（記載順） |
| MOUSE_CURSOR_SIZEALL, MOUSE_CURSOR_SIZENESW, MOUSE_CURSOR_SIZENS, MOUSE_CURSOR_SIZENWSE, MOUSE_CURSOR_SIZEWE, MOUSE_CURSOR_UPARROW, MOUSE_CURSOR_WAIT | 8～14（記載順） |

## Windowの構築と所有

`ckit.Window(...)`は独自のネイティブ窓を作ります。既存OS窓の参照には@ref pyauto_native を使います。
全引数は省略可能でキーワードも使えます。次表の順に位置指定できますが、キーワード指定を推奨します。

| 引数（順序） | 既定値・意味 |
|---|---|
| x, y, width, height, origin | x/yはOS既定位置、width/heightは100/100のクライアント寸法。origin=0は左上基準、ORIGIN_X_*とORIGIN_Y_*のORで枠込み窓の基準点を指定 |
| parent_window | 省略は所有者なし。生存中のckit.Windowか符号なしポインタ幅HWND（0も可）。破棄済み/未初期化WindowはValueError、明示NoneはTypeError。整数HWNDの有効性はWin32が判断する。所有者を無効化/復帰する処理は呼出し側の責任 |
| bg_color, frame_color, caret0_color, caret1_color | 省略時は背景(1, 1, 1)、枠白、非IMEキャレット白、IMEキャレット赤。RGB tuple。キャレット色はXORマスク。明示Noneは不可 |
| border_size, transparency, transparent_color, title_bar, title | border_size=1は現行描画で使われない。transparencyは省略/Noneで無指定、整数0～255で窓全体の不透明度。transparent_colorは省略時無指定のRGB tupleで、transparency整数指定が優先。title_bar=True、titleは省略時空文字列 |
| show, resizable, noframe, minimizebox, maximizebox | 順にTrue, True, False, True, True。整数フラグ。noframeはresizable=False時の枠選択。minimizeboxは独立に反映し、最大化ボタンはmaximizeboxとresizableが共にTrueのとき有効 |
| caret, sysmenu, tool, ncpaint | 全てFalseの整数フラグ。キャレット、システムメニュー、ツール窓、独自非クライアント描画を指定 |
| activate_handlerからnchittest_handler | 下表の順序。省略で未登録。明示Noneを渡すと呼出しを試みてTypeErrorを通知するため、不要なハンドラは省略する |

WindowはPythonラッパーを保持します。変数を捨てるだけでは窓は閉じません。
終了時はfinallyでdestroyを呼びます。所属Planeも破棄され、その後のインスタンス操作はValueErrorです。
destroy自体も再呼出ししません。clearは窓を残して全Planeとキャレット領域を消すため、TextWindowには使用しないでください。
Win32生成失敗はOSError（winerrorを保持、OSエラーが0なら31）で通知し、不完全なWindowを返しません。
Window本体のnew失敗はMemoryError、初回表示中の破棄はRuntimeError、生存中Windowへの再初期化はValueErrorです。
生成失敗時は取得済みのコールバック参照・GDI資源・ネイティブ本体を解放します。
ネイティブWindow.destroyのOS失敗はOSErrorで、HWND・ラッパー・コールバックを保持して再試行できます。
TextWindow等の上位クラスが先に解放した部品までは復元しません。OS側の破棄もラッパーと所属Planeを無効化します。
Reloadは独自窓/タイマーを自動破棄しません。destroyはnchittest_handlerと設定したメニュー木を含む保持参照を解放します。

## Windowの通知（コンストラクター引数順）

ハンドラは保持され、Windowsメッセージ処理中（構築中も含む）に同期呼出しされます。
短く処理し、構築中に未作成の属性へアクセスしないでください。
特記したnchittest_handler以外の戻り値は無視します。例外は通常PyErr_Printで通知され、呼出し元へ伝播しません。
modはMODKEY_ALT/CTRL/SHIFT/WINのビット和。マウス位置は下表で座標系を区別します。

| ハンドラ | 引数・タイミング |
|---|---|
| activate_handler | (active)：アクティブなら整数1、解除なら0 |
| close_handler | ()：閉じる要求。登録すると既定の破棄を置換する。quit等でループを抜け、呼出し側でdestroyする |
| endsession_handler | ()：終了セッションが成立した通知。戻り値で終了を拒否できない |
| move_handler | (x, y)：最小化中を除く枠左上の画面座標 |
| sizing_handler | (size)：ドラッグリサイズ中のクライアント寸法list [width, height]。同じlistの要素を書き換えて寸法を調整する。構築/呼出し/寸法解析の失敗は通知し、元の寸法を使う |
| size_handler | (width, height)：最小化中を除く変更後のクライアント寸法 |
| dpi_handler | (scale)：DPI/96のfloat。DPI・画面・作業領域変更。フォントや配置の更新は利用側で行う |
| dropfiles_handler | (x, y, paths)：クライアント座標とパスstrのlist。ドロップデータは内部で解放済み。各パスはUTF-16の必要長で取得し、切詰めない。空名・取得失敗・Python変換失敗は通知してドロップ全体を破棄し、ハンドラーを呼ばない |
| ipc_handler | (text)：識別値0x101のWM_COPYDATAをUTF-8 strへ変換した内容。長さ0は空str。不正UTF-8、非0長のNULL、引数構築/ハンドラの失敗は通知して当該要求を拒否（応答FALSE）し、次の要求を処理できる |
| keydown_handler, keyup_handler | (vk, mod)：通常/システムキーの仮想キーコード |
| char_handler | (ch, mod)：WM_CHAR/WM_IME_CHARの整数コード単位。補助平面文字を1回の通知と仮定しない |
| lbuttondown_handler, lbuttonup_handler, mbuttondown_handler, mbuttonup_handler, rbuttondown_handler, rbuttonup_handler | (x, y, mod)：クライアント座標の左右中ボタン |
| lbuttondoubleclick_handler, mbuttondoubleclick_handler, rbuttondoubleclick_handler, mousemove_handler | (x, y, mod)：クライアント座標 |
| mousewheel_handler | (x, y, delta, mod)：位置は画面座標。deltaはWHEEL_DELTA単位のfloat（上向き正） |
| nchittest_handler | (x, y)：画面座標。HTCLIENT等のWin32ヒットテストC intを返す。Noneは不可。構築/呼出し/戻り値解析の失敗は通知し、DefWindowProcへ戻す |

## Windowの操作

下表の変更操作はNoneを返し、状態照会はboolです。OSの成否を一律には検査しません。
キーワード可はmessageLoop、setPositionAndSize、popupMenuだけです。静的操作はインスタンス不要です。

| Python署名 | 契約 |
|---|---|
| Window.getHWND() | 借用HWNDのポインタ幅整数。所有権は移らない |
| Window.getHINSTANCE() | 実行モジュールのHINSTANCE整数。解放しない |
| Window.show(show, activate=True) | 整数フラグで表示/非表示。表示時activate=Falseなら非アクティブ表示 |
| Window.enable(enable) | 整数フラグで入力の有効/無効を変更 |
| Window.destroy() | 通知を解除し、HWNDと所属Planeを破棄。再使用不可 |
| Window.activate() | SetActiveWindow。SetFocusや前面化の保証ではない |
| Window.inactivate() | 他の可視・有効・非最前面窓を探して前面化する |
| Window.foreground() | この窓の最終アクティブpopupを前面化する要求 |
| Window.restore() | 通常状態へ復元 |
| Window.maximize() | 最大化 |
| Window.minimize() | 最小化 |
| Window.topmost(topmost) | 整数フラグで最前面状態を変更 |
| Window.isEnabled() | 入力が有効か |
| Window.isVisible() | 可視か |
| Window.isMaximized() | 最大化中か |
| Window.isMinimized() | 最小化中か |
| Window.isActive() | 最後のアクティブ通知の状態 |
| Window.isForeground() | 前面窓か |
| Window.clear() | 全Planeを破棄しキャレット領域を消去。ラッパーも無効になる |
| Window.flushPaint() | dirty領域の描画/転送を実行。失敗はデバッグ出力となる経路があり、Noneは画面提示完了の保証ではない |
| Window.bitBlt() | 診断用。現在のオフスクリーンバッファを直接転送。再描画はしない |
| Window.messageLoop(continue_cond_func) | 同スレッド全窓のメッセージを配送し、破棄/WM_QUIT/quit要求/条件0で終了。条件は引数なしでC intを返す。引数省略で無条件、Noneは呼出し対象。条件例外・不正戻り値は通知して続行するため、例外を終了手段にしない。待機前に条件を評価し、条件変化だけでは待機を起こさない |
| Window.removeKeyMessage() | 呼出しスレッド全体の未処理キー/文字メッセージを除去 |
| Window.quit() | 当該窓の次のループ判定で終了を要求。フラグはそのとき消費。破棄/親復帰はしない |
| Window.getWindowRect() | 枠込み画面(left, top, right, bottom) tuple。最小化中は最後の非最小化矩形 |
| Window.getClientSize() | クライアント(width, height) tuple |
| Window.getNormalWindowRect() | WINDOWPLACEMENT.rcNormalPositionの復元用矩形（通常は作業領域座標、ツール窓は画面座標） |
| Window.getNormalClientSize() | 復元用矩形から現在の枠寸法を引いた(width, height) |
| Window.getDisplayScaling() | この窓のDPI/96のfloat |
| Window.getDisplayScalingFromPosition(x, y) | 静的。画面位置のモニター倍率float。実在モニター上の位置を使う |
| Window.screenToClient(x, y) | 画面→クライアント(x, y) tuple |
| Window.clientToScreen(x, y) | クライアント→画面(x, y) tuple |
| Window.setTimer(func, interval) | func()をintervalミリ秒間隔でUI配送。戻り値無視。同じ関数の多重登録を避ける。実行中の同タイマー再入は抑止 |
| Window.killTimer(func) | 等しい登録関数を先頭1件解除。登録時の関数参照を保持して渡す |
| Window.delayedCall(func, timeout) | func()を1回UI配送。timeoutはミリ秒だが描画タイマーの10ms刻みで減算され実時間の精度保証なし。個別取消APIはない。窓破棄で未実行分を解除 |
| Window.setHotKey(vk, mod, func) | Win32 RegisterHotKeyへ登録しfunc()をUI配送。成功はNone、OS拒否はOSError、ID枯渇はRuntimeError。失敗時は登録・関数参照を残さない。modはWin32 MOD_ALT/CONTROL/SHIFT/WINビット（ckit.MODKEY_*と値が同じ）。多重登録を避ける |
| Window.killHotKey(func) | 等しい関数の登録を先頭1件解除。成功／該当なしはNone。OS失敗はOSErrorで登録・参照を保持し、比較例外も伝播 |
| Window.setImeRect(rect) | クライアント(left, top, right, bottom) tuple。Noneはゼロ矩形にしてキャレット位置を使用 |
| Window.enableIme(enable) | IMEコンテキストを切替。再有効化時は閉じた状態にする。IME変換操作を代行しない |
| Window.setPositionAndSize(x, y, width, height, origin) | 構築時と同じ画面基準点・クライアント寸法へ移動/変更。5引数全て必要 |
| Window.setTitle(title) | タイトルstrを変更 |
| Window.setBGColor(rgb) | 背景色を変更し再描画要求 |
| Window.setFrameColor(rgb) | 枠色。Noneは変更しない |
| Window.setCaretColor(rgb0, rgb1) | 非IME/IMEのXOR色。両方RGB tupleなら変更。Noneを含む場合は変更しない |
| Window.setMenu(root) | MenuNodeのルートを保持。Noneで外す。同じrootの再設定は再構築せず、メニュー開始時に更新 |
| Window.setCapture() | マウスキャプチャ開始 |
| Window.releaseCapture() | 自窓が所有するときだけキャプチャ解除 |
| Window.setMouseCursor(id) | MOUSE_CURSOR_*整数定数のカーソルを設定。未知値は無操作 |
| Window.drag(x, y) | 画面位置からタイトルバードラッグを非同期要求。各座標は符号付き16bit（-32768～32767）、範囲外は下位16bitを使用 |
| Window.popupMenu(x, y, items) | 画面位置のOSメニュー。itemsは(label, command[, checked]) tupleのsequence。label="-"は区切り、checkedは省略/厳密なbool。選択時command(info)、戻り値無視。Noneは取消も表す。過多項目はValueError。コマンド参照は次回表示/窓破棄まで保持 |
| Window.enumFonts() | 静的。列挙フィルターに合う非縦書きフォント名のソート済み重複なしlist[str]。全フォント一覧ではない |
| Window.sendIpc(hwnd, data) | 静的。ポインタ幅HWNDへWM_COPYDATAを同期送信。dataはUTF-8へ変換されるstrか読取専用bytes互換バッファ。受信側はstrへ復号するため有効なUTF-8にする。最大DWORD長、タイムアウトなし。応答/実行結果を返さない |

タイマー/遅延/ホットキーは関数を保持し、戻り値を無視し、例外を通知します。窓破棄で登録参照を解除します。
窓破棄はヒットテスト関数とメニュー木も解放し、参照解放による再入より先にラッパーを無効化します。
コールバックから窓を破棄した場合もラッパーは直ちに無効となり、後続コールバックを抑止します。
実行中のネイティブ処理が戻るまで本体と登録参照を保持し、最後の処理が戻った時点で解放します。

## Font・Attribute・Image

| Python署名 | 契約 |
|---|---|
| ckit.Font(name, size, vertical_padding=0) | 位置引数のみ。nameは32 UTF-16単位未満のstr（NUL不可）、sizeはGDI文字高のピクセル整数。上下に各max(padding, 0)ピクセル追加。通常は正のsizeを使う。過長/NULはValueError、整数/セル高超過はOverflowError、GDI作成/計測失敗はRuntimeError、メモリ失敗はMemoryError。参照所有で解放され、destroyはない。通常はgetStockedFontを使える |
| Font.getCharSize() | (width, height)のセル寸法tuple。heightは上下padding込み |
| ckit.Attribute(fg省略可, bg省略可, bg_gradation省略可, line0省略可, line1省略可) | キーワード可。描画属性の値を作る。fg/bgはRGB tuple、bg_gradationは左上・右上・左下・右下のRGB 4個tupleでbgより優先。line0/line1は(LINE_*ビット和, RGB) tuple。省略/Noneは当該指定なし。Python構築の未指定フィールドはゼロであり、fgは必要な色を明示する。属性の読書きAPIはなく、変更は新しいAttributeを作る |
| Image.fromBytes(size, pixels, transparent_color=None, halftone=False) | 静的、位置引数のみ。sizeは(width, height)、pixelsは上段から連続したRGBA 4バイト/画素の読取専用bytes互換バッファ。短いバッファはValueError、バイト数がPy_ssize_t範囲を超えるとOverflowError。幅または高さが0以下なら(0, 0)の空画像。確保失敗はMemoryError、GDI作成/転送失敗はRuntimeError。transparent_colorはRGBの色キーでalpha合成ではない。halftoneは拡大縮小の補間フラグ。新Imageを返し元バッファを保持しない。Image()やImage.__new__()による直接生成はTypeError。fromBytesで生成する |
| Image.getSize() | (width, height)ピクセルtuple。Imageは参照所有で解放され、destroyはない |

Imageはpyauto.Imageと別型です。alphaチャネルを渡してもImagePlaneはalpha合成しません。
RGB値の範囲や渡されたネイティブ型を包括的に検証するAPIではありません。指定された型と実用的な寸法を使ってください。

## TextPlane・ImagePlane

`ckit.TextPlane(window, (x, y), (width, height), priority)`と
`ckit.ImagePlane(window, (x, y), (width, height), priority)`は位置引数のみ。
windowは生存中のckit.Window、位置はクライアント内、寸法はピクセル、priorityはfloatです。
大きいpriorityから描画し、小さい値が前面になります。構築後は表示フラグTrue、内容/Fontは未設定です。
windowがPlaneとPythonラッパーを保持し、Plane.destroyまたはwindow.clear/destroyで解除します。
前者のdestroyを二重に呼ぶことや、親破棄後の操作はValueErrorです。
setPriorityは所属リストの描画順を更新して再描画を要求します。同値のpriority間は変更直前の相対順を保持し、同じ値の再設定は無操作です。
以下の変更操作はNone、取得操作は表記した値を返します。putStringだけキーワード可です。

| Python署名 | 契約 |
|---|---|
| TextPlane.destroy(), ImagePlane.destroy() | 所属リストから外して資源を解放 |
| TextPlane.show(show), ImagePlane.show(show) | 整数フラグで表示切替 |
| TextPlane.getPosition(), ImagePlane.getPosition() | クライアント(x, y)ピクセルtuple |
| TextPlane.setPosition(position), ImagePlane.setPosition(position) | 1個の(x, y) tupleで配置 |
| TextPlane.getSize(), ImagePlane.getSize() | (width, height)ピクセルtuple |
| TextPlane.setSize(size), ImagePlane.setSize(size) | 1個の(width, height) tupleで変更 |
| TextPlane.getPriority(), ImagePlane.getPriority() | float |
| TextPlane.setPriority(priority), ImagePlane.setPriority(priority) | priorityと描画順を変更し、再描画を要求 |
| TextPlane.getFont() | 未設定ならNone、設定済みなら同じネイティブFontを共有する新しいPythonラッパー。isによる同一性は保証しない |
| TextPlane.setFont(font) | ckit.Fontを保持。None不可。描画を無効化して次回更新 |
| ImagePlane.getImage() | 未設定ならNone、設定済みなら同じネイティブImageを共有する新ラッパー |
| ImagePlane.setImage(image) | ckit.Imageを保持しPlaneの寸法へ拡大縮小描画。None不可 |
| TextPlane.putString(x, y, width, height, attr, str, offset=0) | ここだけ座標/寸法/offsetは文字セル。Attributeと文字列でyの1行を描画し、[x, x+width)とPlaneの完全なセル範囲の交差でクリップ。heightは複数行描画ではなくdirty領域の高さ。offsetはxからの横位置のずらし、負数はxより左を切り取る。端に片側だけかかる倍幅文字は属性付き空白。タブ展開/改行分割はしない。負のx/y、幅/高さ0以下、空文字列は無操作。例外条件と保持範囲は下記参照 |
| TextPlane.scroll(x, y, width, height, delta_x, delta_y) | セル矩形をセル単位で移動。露出部分の再描画は利用側。縦移動時の文字バッファは従来どおり行単位でコピー。x/y/寸法と移動先は非負（違反はValueError）。寸法0または移動量0は無操作。セル終端・ピクセル座標の桁あふれはOverflowError、確保失敗はMemoryError |
| TextPlane.getCharSize() | Fontの(width, height)ピクセルtuple |
| TextPlane.charToScreen(x, y) | セル→画面ピクセルtuple |
| TextPlane.charToClient(x, y) | セル→所有Windowのクライアントピクセルtuple |
| TextPlane.getStringWidth(str, tab_width=4, offset=0) | 表示セル幅整数。tab_widthは正整数（0以下はValueError）。offsetはタブ展開開始セル（負値可）、返却幅はoffsetを含まない。計測幅のC int上限超過はOverflowError |
| TextPlane.getStringColumns(str, tab_width=4, offset=0) | 各UTF-16単位開始と末尾の相対セル列tuple（UTF-16長+1）。先頭は0、末尾はgetStringWidthと同じ。offsetはタブ展開開始セル。tab_widthは正整数（0以下はValueError）。補助平面文字はPython文字位置と異なるためTextWidgetが対応付ける。NULを含めない。UTF-16長はINT_MAX未満、計測幅はINT_MAX以下。上限超過はOverflowError、変換・配列・tuple・要素の確保失敗はMemoryError |
| TextPlane.setCaretPosition(x, y) | セル位置へ所有窓のキャレット/IMEフォントを設定。(-1, -1)は空矩形でキャレットを非表示にする。それ以外の負数は通常どおり座標変換し、Planeの表示範囲では制限しない。窓はcaret=Trueで構築する |

putString・scroll・getCharSize・charToScreen・charToClient・getStringWidth・getStringColumns・setCaretPositionは
Font未設定ならValueError。描画自体は未設定Planeを飛ばします。文字幅/描画はUTF-16単位の単幅/倍幅処理で、
複雑な組版を保証しません。保持した内容は必要に応じて所有窓の描画タイマー/flushPaintで画面へ反映されます。

putStringは描画領域と現在のPlaneセル範囲の外への書込みを保持しません。後でPlaneを拡大しても、
その呼出しで範囲外だった描画内容は復元されず、再描画が必要です。セル範囲はPlaneのピクセル寸法をFontのセル寸法で整数除算したものです。
xが右端以降、yが最終行の次以降、またはx+offsetがクリップ後の右端以降の場合も無操作です。

putStringの整数引数x/y/width/height/offsetは符号付き32bit C intの範囲外なら、引数解析時にOverflowErrorです。
それらが範囲内でも、上記の無操作条件を通過した場合、更新矩形のピクセル座標を検査します。
cw/chをセルのピクセル寸法、px/pyをPlane位置、cols/rowsをPlaneセル数とすると、
左=px+x*cw、上=py+y*ch、右=px+min(x+width, cols)*cw、下=py+min(y+height, rows)*chです。
左または上がINT_MIN未満、右または下がINT_MAX超過ならOverflowErrorです。
セル終端やx+offsetの加算自体は64bitで計算し、C int超過だけでは拒否しません。文字バッファの確保失敗はMemoryErrorです。

## MenuNode・TaskTrayIcon

`ckit.MenuNode(name省略可, text省略可, command省略可, visible省略可, enabled省略可, checked省略可, items省略可, separator=False)`はキーワード可。
name/textは省略時空文字列。root.itemsにトップレベルMenuNodeのlist/tuple、そのitemsに子を置きWindow.setMenuへ渡します。
itemsありはサブメニュー、separator=Trueは区切り、それ以外の葉はcommand(info)を実行します。
command等の不要なコールバック/itemsは省略してください。明示Noneは未指定と同じ内部状態ではありません。
visible()/enabled()/checked()はC int（bool可）を返し、表示/有効/チェックを決めます。
呼出し/戻り値解析の失敗は通知してクリアし、visibleは表示、enabledは親からの有効状態、checkedは未チェックという既定を使います。
子sequenceの長さ/要素取得の失敗は通知し、そのsequenceの構築を中止します。既に追加した項目は保持し、次回開始時に再構築します。
トップレベルではvisible/checked/区切り/葉のcommandを評価せず、enabledは子へ継承します。
子itemsの要素には引数なしで子sequenceを返すcallableも置けます。メニュー作成/開始時にUIスレッドで評価し、例外は通知します。
選択時infoは本体登録の新しいCommandInfo（未登録ならNone）で、コマンド戻り値は無視します。
公開読書き属性はname（str）とitems（渡した参照、未指定ならNone）だけ。他属性の取得/変更はAttributeErrorです。
メニュー木とコールバックは参照保持されます。setMenu(None)または窓破棄で外し、保持した参照も手放します。循環参照を作らないでください。

`ckit.TaskTrayIcon(title省略可, lbuttondown_handler省略可, lbuttonup_handler省略可, rbuttondown_handler省略可, rbuttonup_handler省略可, lbuttondoubleclick_handler省略可)`もキーワード可。
titleは空文字列が既定のツールチップで、最大127 UTF-16コード単位です（補助平面文字は2単位）。超過はOS操作前にValueErrorです。
受信窓の生成失敗はWindowsエラー付きOSErrorで、保持したハンドラ参照を解放し通知領域への登録は行いません。
ハンドラは省略で未登録、引数(x, y, mod)、戻り値無視、例外通知。現行実装のx/yは通知メッセージ値から生成し、
カーソル座標としては使えません。必要ならpyauto.Input.getCursorPos()を取得します。
通知領域への登録がタイムアウト／エラーコードなしで失敗した場合、UIのメッセージループで1秒間隔に再試行します。
再試行前にNIM_MODIFYで登録済みか確認し、構築やExplorer再起動通知の処理内では再試行待ちをしません。
メッセージループの実行が必要です。他の登録エラーやタイマー生成失敗は診断を出して再試行を停止し、Explorer再起動通知では再登録します。
OS登録の成否を返さず、ラッパーを手放すだけでは終了しないためdestroyを呼びます。
destroyはラッパーを先に無効化し、ハンドラ・ポップアップコマンド・ラッパーの所有参照を解放します。破棄後のdestroy/popupMenuはValueErrorです。
生存中のラッパーへのTaskTrayIcon.__init__再実行は、既存資源を変えずValueErrorで拒否します。destroy完了後は再初期化できます。

| Python署名 | 契約 |
|---|---|
| TaskTrayIcon.destroy() | アイコンと受信窓を解除し所有参照を解放。再呼出しはValueError |
| TaskTrayIcon.popupMenu(x, y, items) | キーワード可。Window.popupMenuと同じ項目形式・画面座標・command(info)・None戻り値・参照保持。同一アイコンの実行中の再入は引数変換前にValueErrorで拒否し、外側のメニューを維持。正常終了・取消・例外後は再表示可。別アイコンは制限しない |

## Lineと初期化/診断用関数

`ckit.Line(s)`はTextWidgetの行データです。キーワードsも可。strから末尾CRLF/CR/LFを1組分離します。
NUL/補助平面文字も保持し、メソッドはありません。以下は読書き属性です。文字列/キャッシュを直接変えても文書通知は行わず、
通常の編集はTextWidget.modifyTextを使います。未定義属性はAttributeErrorです。

| 属性 | 初期値・制約 |
|---|---|
| s | 改行を除く本文str。代入では型/改行を自動処理しないためstrを保持する |
| end | 分離した改行、または空str。代入はstr必須で末尾だけからCRLF/CR/LF/空を判定 |
| ctx, tokens | 構文キャッシュ、初期None。任意Python参照を保持 |
| bg | 0、背景番号は0～3のint（bool・int派生型も可） |
| bookmark | 0、番号/ビット値は0～7のint（bool・int派生型も可） |
| modified | False、代入も厳密なTrue/Falseだけ |

bg/bookmarkの代入は非intをTypeError、C long変換の桁あふれをOverflowError、それ以外の値域違反をValueErrorにします。失敗時は他のフラグを含む全属性を保持します。

次の関数は本体の初期化/診断用にも再公開されています。custom.pyで通常呼び直す必要はありません。
全て位置引数のみ、戻り値None。Errorは公開例外型ですが各操作で一律に使うものではありません。

| Python署名 | 契約 |
|---|---|
| ckit.registerWindowClass(prefix) | prefix strにWindowClass/TaskTrayWindowClassを付けて登録。初回窓作成前に1回。本体が実施済み。再登録等の失敗はOSError。プロセス全体のクラス名を変更する |
| ckit.registerCommandInfoConstructor(constructor) | メニュー選択時に引数なしで呼ぶ生成関数をプロセス全体で保持/置換。本体がCommandInfoを登録済み。Noneは解除指定にならない |
| ckit.enableBlockDetector(report_func) | 引数なし通知関数をプロセス全体で保持するだけ。ここでは監視を開始しない |
| ckit.setBlockDetector() | 登録済み通知関数があれば現スレッドへPythonプロファイラーを設定。プロファイルイベント間が1000ms超のときreport_func()。戻り値無視、例外通知。完全な停止検出や実行時間測定ではなく他プロファイラーを置換。停止は同スレッドのsys.setprofile(None) |
@endcond
*/

/**
@cond english
@page ckit_native Native ckit APIs

Native components exposed by import ckit. Prefer TextWindow in @ref widget for ordinary text windows,
and @ref textwidget for multiline editing. This page covers their foundation and low-level drawing.
Tables omit self and prefix instance operations with the type (call plane.setFont(font), etc.).
Unless stated otherwise, integers fit C int, colors are RGB tuples of three integers in 0..255, and coordinates/sizes are pixels.
Strings are str without NUL (except Line and length-delimited sendIpc); embedded NUL raises ValueError. Arguments are positional unless keyword support is stated.
Argument parsing failures raise TypeError/OverflowError. Do not pass None or unrelated types where native objects are required:
not every native boundary validates the object type. Operate Window/Plane/TaskTrayIcon and callbacks on their creating UI thread;
marshal worker requests back through SyncCall or an equivalent UI dispatch. See @ref extensions for a complete example.

The ckit constants used on this page have the following values. OR one horizontal and one vertical ORIGIN choice.
Add LINE_DOT to the desired edge flags.

| Constants | Values |
|---|---|
| ORIGIN_X_LEFT, ORIGIN_X_CENTER, ORIGIN_X_RIGHT | 0, 1, 2 |
| ORIGIN_Y_TOP, ORIGIN_Y_CENTER, ORIGIN_Y_BOTTOM | 0, 4, 8 |
| MODKEY_ALT, MODKEY_CTRL, MODKEY_SHIFT, MODKEY_WIN | 1, 2, 4, 8 |
| LINE_LEFT, LINE_RIGHT, LINE_TOP, LINE_BOTTOM, LINE_DOT, LINE_RECTANGLE | 1, 2, 4, 8, 16, 15 |
| MOUSE_CURSOR_APPSTARTING, MOUSE_CURSOR_ARROW, MOUSE_CURSOR_CROSS, MOUSE_CURSOR_HAND, MOUSE_CURSOR_HELP, MOUSE_CURSOR_IBEAM, MOUSE_CURSOR_NO | 1..7 in order |
| MOUSE_CURSOR_SIZEALL, MOUSE_CURSOR_SIZENESW, MOUSE_CURSOR_SIZENS, MOUSE_CURSOR_SIZENWSE, MOUSE_CURSOR_SIZEWE, MOUSE_CURSOR_UPARROW, MOUSE_CURSOR_WAIT | 8..14 in order |

## Window construction and ownership

`ckit.Window(...)` creates a native window. Use @ref pyauto_native to refer to an existing OS window.
All arguments are optional and accept keywords. Positional order is shown below; prefer keywords.

| Arguments (in order) | Defaults and meaning |
|---|---|
| x, y, width, height, origin | x/y default to the OS position; width/height are 100/100 client pixels. origin=0 anchors the outer top-left; OR the ORIGIN_X_* and ORIGIN_Y_* bits for other outer-window anchors |
| parent_window | Omitted means no owner. Accept a live ckit.Window or unsigned pointer-width HWND (including 0). A destroyed/uninitialized Window raises ValueError; explicit None raises TypeError. Win32 determines integer HWND validity. The caller owns disabling/restoring the parent |
| bg_color, frame_color, caret0_color, caret1_color | Omitted defaults: (1, 1, 1) background, white frame, white non-IME caret and red IME caret. RGB tuples; caret colors are XOR masks. Explicit None is invalid |
| border_size, transparency, transparent_color, title_bar, title | border_size=1 is unused in current painting. Omitted/None transparency means unspecified; integer 0..255 sets whole-window opacity. transparent_color is an optional RGB color key; integer transparency takes precedence. title_bar=True; omitted title is empty |
| show, resizable, noframe, minimizebox, maximizebox | Integer flags default to True, True, False, True, True. noframe affects framing when resizable=False. minimizebox applies independently; the maximize button requires both maximizebox and resizable |
| caret, sysmenu, tool, ncpaint | Integer flags, all False: caret, system menu, tool window, custom non-client painting |
| activate_handler through nchittest_handler | In the order of the callback table. Omit unused callbacks. Explicit None is retained and called, causing a reported TypeError |

A Window retains its Python wrapper; dropping a variable does not close it. Call destroy in finally.
It also destroys owned Planes; subsequent instance operations raise ValueError. Do not call destroy twice.
clear leaves the window alive but destroys every Plane and clears the caret rectangle; do not use it on TextWindow.
Win32 creation failure raises OSError (preserving winerror, or 31 if the OS error is zero) and never returns an incomplete Window.
Failure to allocate the native Window block raises MemoryError; destruction during initial show raises RuntimeError; reinitializing a live Window raises ValueError.
Failed construction releases acquired callback references, GDI resources and the native object.
An OS failure in native Window.destroy raises OSError and retains the HWND, wrapper and callbacks for retry.
It does not restore controls already released by subclasses such as TextWindow. OS destruction also invalidates the wrapper and owned Planes.
Reload does not automatically release custom windows/timers. destroy releases retained references, including nchittest_handler and an assigned menu tree.

## Window callbacks (constructor order)

Callbacks are retained and invoked synchronously during Windows message handling, including construction.
Keep them short and avoid accessing attributes that do not yet exist during construction.
Return values are ignored except for nchittest_handler. Exceptions are normally reported by PyErr_Print rather than propagated to the caller.
mod combines MODKEY_ALT/CTRL/SHIFT/WIN bits. Mouse coordinate systems differ as shown below.

| Callback | Arguments and timing |
|---|---|
| activate_handler | (active): integer 1 on activation, 0 on deactivation |
| close_handler | (): close request. Replaces default destruction. Use quit to leave the loop and let the caller destroy |
| endsession_handler | (): successful end-session notification; cannot veto shutdown through a return value |
| move_handler | (x, y): outer top-left screen pixels, except while minimized |
| sizing_handler | (size): mutable client-size list [width, height] during resize dragging. Modify the same list to adjust the size. Report construction/call/size parsing failures and use the original size |
| size_handler | (width, height): new client pixel size, except while minimized |
| dpi_handler | (scale): float DPI/96 on DPI, display or work-area changes. The caller updates fonts/layout |
| dropfiles_handler | (x, y, paths): client pixels and a list of path strings; native drop data has already been released. Each path is retrieved at its required UTF-16 length without truncation. An empty name, retrieval failure or Python conversion failure is reported and discards the entire drop without calling the handler |
| ipc_handler | (text): WM_COPYDATA with identifier 0x101, decoded from UTF-8 to str; zero length becomes an empty str. Report invalid UTF-8, nonzero length with NULL, argument construction or handler failure; reject that request (FALSE response) and allow the next request |
| keydown_handler, keyup_handler | (vk, mod): virtual key for normal/system key messages |
| char_handler | (ch, mod): integer WM_CHAR/WM_IME_CHAR code unit; supplementary characters need not arrive as one callback |
| lbuttondown_handler, lbuttonup_handler, mbuttondown_handler, mbuttonup_handler, rbuttondown_handler, rbuttonup_handler | (x, y, mod): client pixels for left/middle/right buttons |
| lbuttondoubleclick_handler, mbuttondoubleclick_handler, rbuttondoubleclick_handler, mousemove_handler | (x, y, mod): client pixels |
| mousewheel_handler | (x, y, delta, mod): screen pixels; float delta in WHEEL_DELTA units, positive upward |
| nchittest_handler | (x, y): screen pixels. Return a Win32 hit-test C int such as HTCLIENT, never None. Report construction/call/result parsing failures and fall back to DefWindowProc |

## Window operations

Mutating operations below return None; state predicates return bool. OS success is not uniformly checked.
Only messageLoop, setPositionAndSize and popupMenu accept keywords. Static operations require no instance.

| Python signature | Contract |
|---|---|
| Window.getHWND() | Borrowed pointer-width HWND integer; no ownership transfer |
| Window.getHINSTANCE() | Executable module HINSTANCE integer; do not free |
| Window.show(show, activate=True) | Integer flags for visibility; activate=False shows without activation |
| Window.enable(enable) | Integer flag enabling/disabling input |
| Window.destroy() | Release callbacks, HWND and owned Planes; no further use |
| Window.activate() | SetActiveWindow; does not guarantee SetFocus or foreground activation |
| Window.inactivate() | Find another visible, enabled, non-topmost window and bring it forward |
| Window.foreground() | Request foreground activation of this window's last active popup |
| Window.restore() | Restore normal state |
| Window.maximize() | Maximize |
| Window.minimize() | Minimize |
| Window.topmost(topmost) | Integer flag for always-on-top state |
| Window.isEnabled() | Whether input is enabled |
| Window.isVisible() | Whether visible |
| Window.isMaximized() | Whether maximized |
| Window.isMinimized() | Whether minimized |
| Window.isActive() | State from the last activation notification |
| Window.isForeground() | Whether the foreground window |
| Window.clear() | Destroy all Planes, invalidating wrappers, and clear the caret rectangle |
| Window.flushPaint() | Paint/transfer dirty areas. Some failures go to debug output; None does not guarantee display presentation |
| Window.bitBlt() | Diagnostic transfer of the existing offscreen buffer without repainting |
| Window.messageLoop(continue_cond_func) | Dispatch all windows on the same thread until destruction, WM_QUIT, quit or condition 0. Optional no-argument condition must return C int. Omitted argument means unconditional; None is called. Condition exceptions and invalid results are reported and the loop continues, so do not use exceptions to exit. Checked before waiting; changing the condition alone does not wake the wait |
| Window.removeKeyMessage() | Remove pending key/character messages for the entire calling thread |
| Window.quit() | Request exit at this window's next loop check, consuming the flag there. Does not destroy or restore a parent |
| Window.getWindowRect() | Outer screen (left, top, right, bottom) tuple; last non-minimized rectangle while minimized |
| Window.getClientSize() | Client (width, height) tuple |
| Window.getNormalWindowRect() | Restore rectangle from WINDOWPLACEMENT.rcNormalPosition, normally workspace coordinates (screen coordinates for tool windows) |
| Window.getNormalClientSize() | Restore rectangle minus current frame dimensions, as (width, height) |
| Window.getDisplayScaling() | Float window DPI/96 |
| Window.getDisplayScalingFromPosition(x, y) | Static float scale at a screen position; use a point on an actual monitor |
| Window.screenToClient(x, y) | Screen to client pixel tuple |
| Window.clientToScreen(x, y) | Client to screen pixel tuple |
| Window.setTimer(func, interval) | Dispatch func() on the UI every interval milliseconds, ignoring its return. Avoid duplicate registrations of one function. Suppress reentry of the same running timer |
| Window.killTimer(func) | Remove the first equal callback registration; keep and pass the registered function reference |
| Window.delayedCall(func, timeout) | Dispatch func() once on the UI. Millisecond timeout decreases in 10ms paint-timer steps, not guaranteed wall time. No individual cancellation API; destruction releases pending calls |
| Window.setHotKey(vk, mod, func) | Register a Win32 global hotkey and dispatch func() on the UI. Return None on success; raise OSError on OS rejection or RuntimeError on ID exhaustion. Failure retains no registration or callback reference. mod uses Win32 MOD_ALT/CONTROL/SHIFT/WIN bits (same values as ckit.MODKEY_*). Avoid duplicate registration |
| Window.killHotKey(func) | Remove the first registration with an equal callback. Return None on success or no match. OS failure raises OSError and keeps the registration/reference; comparison errors propagate |
| Window.setImeRect(rect) | Client (left, top, right, bottom) tuple. None resets to zero, using caret position |
| Window.enableIme(enable) | Switch IME context; re-enabling closes its open status. Does not perform composition |
| Window.setPositionAndSize(x, y, width, height, origin) | Same screen anchor/client pixel sizes as construction; all five arguments required |
| Window.setTitle(title) | Set title str |
| Window.setBGColor(rgb) | Change background and request repaint |
| Window.setFrameColor(rgb) | Frame color; None leaves unchanged |
| Window.setCaretColor(rgb0, rgb1) | Non-IME/IME XOR colors. Change only when both are RGB tuples; a None leaves unchanged |
| Window.setMenu(root) | Retain a MenuNode root; None removes it. Reassigning the same root does not rebuild; refresh occurs when opening the menu |
| Window.setCapture() | Start mouse capture |
| Window.releaseCapture() | Release capture only if owned by this window |
| Window.setMouseCursor(id) | Set a MOUSE_CURSOR_* integer cursor; unknown values do nothing |
| Window.drag(x, y) | Asynchronously request a title-bar drag from screen pixels. Each coordinate is signed 16-bit (-32768..32767); values outside this range use the low 16 bits |
| Window.popupMenu(x, y, items) | OS menu at screen pixels. items is a sequence of (label, command[, checked]) tuples. label="-" is a separator; checked is omitted or strictly bool. Selection calls command(info), ignoring its return. None also covers cancellation. Excess items raise ValueError. Callback references persist until the next popup or destruction |
| Window.enumFonts() | Static sorted list[str] of unique non-vertical names passing the font filter; not every installed font |
| Window.sendIpc(hwnd, data) | Static synchronous WM_COPYDATA to pointer-width HWND. data is str converted to UTF-8 or a read-only bytes-compatible buffer. Receiver decodes to str, so supply valid UTF-8. Maximum DWORD length, no timeout. No reply/execution result |

Timers, delayed calls and hotkeys retain callbacks, ignore returns and report exceptions. Destruction releases registrations.
Destruction also releases the hit-test callback and menu tree, invalidating the wrapper before reference-release finalizers can reenter.
Destruction from a callback immediately invalidates the wrapper and suppresses subsequent callbacks.
The native object and registered references remain alive until the last active native operation returns, then are released.

## Font, Attribute and Image

| Python signature | Contract |
|---|---|
| ckit.Font(name, size, vertical_padding=0) | Positional only. name is str shorter than 32 UTF-16 units, without NUL. size is integer GDI character height in pixels, normally positive. Add max(padding, 0) pixels on each vertical side. Excess name/NUL raises ValueError; integer/cell-height overflow raises OverflowError; GDI creation/measurement failure raises RuntimeError; allocation failure raises MemoryError. Reference-owned, no destroy. Usually use getStockedFont |
| Font.getCharSize() | Cell (width, height) tuple, including vertical padding |
| ckit.Attribute(fg optional, bg optional, bg_gradation optional, line0 optional, line1 optional) | Keywords supported. Construct a drawing value: fg/bg are RGB tuples; bg_gradation is four RGB tuples in top-left, top-right, bottom-left, bottom-right order and overrides bg. line0/line1 are (LINE_* bit mask, RGB) tuples. Omitted/None means unspecified. Unspecified Python-constructed fields are zero; explicitly supply the desired foreground. No field read/write API; construct a new Attribute for changes |
| Image.fromBytes(size, pixels, transparent_color=None, halftone=False) | Static, positional only. size is (width, height), pixels is contiguous top-down RGBA, four bytes/pixel, in a read-only bytes-compatible buffer. Short buffers raise ValueError; byte counts exceeding Py_ssize_t raise OverflowError. Nonpositive width or height produces an empty (0, 0) image. Allocation failure raises MemoryError; GDI creation/transfer failure raises RuntimeError. transparent_color is an RGB color key, not alpha blending; halftone selects scaling interpolation. Return a new Image without retaining the source buffer. Direct construction through Image() or Image.__new__() raises TypeError; use fromBytes |
| Image.getSize() | Pixel (width, height) tuple. Reference-owned, no destroy |

Image and pyauto.Image are different types. Passing alpha does not make ImagePlane alpha-blend.
The API does not comprehensively validate RGB ranges or supplied native types; use the documented types and practical dimensions.

## TextPlane and ImagePlane

`ckit.TextPlane(window, (x, y), (width, height), priority)` and
`ckit.ImagePlane(window, (x, y), (width, height), priority)` are positional-only constructors.
window is a live ckit.Window, position is client pixels, size is pixels and priority is float.
Larger priorities paint first; smaller ones appear in front. Initially visible, without contents/font.
The window retains the Plane and Python wrapper until Plane.destroy or window.clear/destroy.
Double destruction and operations after owner destruction raise ValueError.
setPriority updates the owning list's drawing order and requests repaint. Equal priorities retain their relative order from before the change; assigning the same value does nothing.
Mutators return None; getters return the values below. Only putString accepts keywords.

| Python signature | Contract |
|---|---|
| TextPlane.destroy(), ImagePlane.destroy() | Remove from owner list and release resources |
| TextPlane.show(show), ImagePlane.show(show) | Integer visibility flag |
| TextPlane.getPosition(), ImagePlane.getPosition() | Client (x, y) pixel tuple |
| TextPlane.setPosition(position), ImagePlane.setPosition(position) | One (x, y) tuple |
| TextPlane.getSize(), ImagePlane.getSize() | (width, height) pixel tuple |
| TextPlane.setSize(size), ImagePlane.setSize(size) | One (width, height) tuple |
| TextPlane.getPriority(), ImagePlane.getPriority() | Float priority |
| TextPlane.setPriority(priority), ImagePlane.setPriority(priority) | Change priority and drawing order; request repaint |
| TextPlane.getFont() | None before assignment; otherwise a new Python wrapper sharing the native Font, without an is-identity guarantee |
| TextPlane.setFont(font) | Retain ckit.Font, not None; invalidate painting for the next update |
| ImagePlane.getImage() | None before assignment; otherwise a new wrapper sharing the native Image |
| ImagePlane.setImage(image) | Retain ckit.Image, not None, and scale it to the Plane's pixel size |
| TextPlane.putString(x, y, width, height, attr, str, offset=0) | Here coordinates, sizes and offset are cells. Draw one row at y using an Attribute and str, clipped to the intersection of [x, x+width) and the Plane's complete cells. height describes dirty-area height, not multiline output. offset shifts text from x; negative values clip text left of x. A double-cell character crossing either edge becomes an attributed space. No tab expansion/newline splitting. Negative x/y, nonpositive width/height and empty text do nothing. See exceptions and retention below |
| TextPlane.scroll(x, y, width, height, delta_x, delta_y) | Move a cell rectangle by cell offsets; caller repaints exposed areas. Vertical moves retain the whole-line character-buffer copy. x/y/dimensions and destination must be nonnegative (otherwise ValueError). Zero dimensions or zero movement do nothing. Cell-endpoint/pixel overflow raises OverflowError; allocation failure raises MemoryError |
| TextPlane.getCharSize() | Font cell (width, height) pixels |
| TextPlane.charToScreen(x, y) | Cell to screen-pixel tuple |
| TextPlane.charToClient(x, y) | Cell to owner-client-pixel tuple |
| TextPlane.getStringWidth(str, tab_width=4, offset=0) | Integer cell width excluding offset. tab_width must be positive (otherwise ValueError). offset is the starting cell for tabs, including negative values. Measured widths above C int raise OverflowError |
| TextPlane.getStringColumns(str, tab_width=4, offset=0) | Relative cell-column tuple for each UTF-16 unit start and the end, length UTF-16 length+1. Starts at 0 and ends at getStringWidth. offset is the starting cell for tabs. tab_width must be positive (otherwise ValueError). TextWidget maps supplementary characters to Python indices. Exclude NUL. UTF-16 length must be below INT_MAX and measured width at most INT_MAX; exceeding either raises OverflowError. Conversion, array, tuple or item allocation failures raise MemoryError |
| TextPlane.setCaretPosition(x, y) | Set the owner caret at cells and its IME font. (-1, -1) hides the caret with an empty rectangle. Other negative values undergo normal coordinate conversion, without clipping to the Plane's visible area. Construct the window with caret=True |

putString, scroll, getCharSize, charToScreen, charToClient, getStringWidth, getStringColumns and setCaretPosition
raise ValueError without a font. Painting skips fontless Planes. Text is measured/drawn as UTF-16 single/double-cell units,
without a complex typesetting guarantee. Retained contents are presented by the owner paint timer/flushPaint.

putString does not retain writes outside the drawing area or the current Plane cells. Enlarging the Plane later
does not restore content that was outside these bounds during that call; redraw it. Cell bounds are the Plane's pixel dimensions divided by the Font's cell dimensions using integer division.
Also do nothing when x is at or beyond the right edge, y is beyond the last row, or x+offset is at or beyond the clipped right edge.

Integer arguments x/y/width/height/offset outside signed 32-bit C int raise OverflowError during argument parsing.
Even with arguments in range, calls that pass the above no-op conditions validate the dirty rectangle's pixel coordinates.
With cell pixel dimensions cw/ch, Plane position px/py and Plane cell counts cols/rows,
left=px+x*cw, top=py+y*ch, right=px+min(x+width, cols)*cw, bottom=py+min(y+height, rows)*ch.
Raise OverflowError if left or top is below INT_MIN, or right or bottom exceeds INT_MAX.
Cell endpoints and x+offset are computed in 64 bits; exceeding C int in those additions alone is not rejected. Character-buffer allocation failures raise MemoryError.

## MenuNode and TaskTrayIcon

`ckit.MenuNode(name optional, text optional, command optional, visible optional, enabled optional, checked optional, items optional, separator=False)` accepts keywords.
name/text default to empty strings. Put top-level MenuNodes in root.items as a list/tuple, their children in their items, and pass the root to Window.setMenu.
items defines a submenu; separator=True a separator; other leaves call command(info).
Omit unused callbacks/items: explicit None is not the same internal state as omission.
visible()/enabled()/checked() return C int (bool is accepted) for visibility/enabled/check state.
Report and clear call/result parsing failures, keeping the defaults: visible, enabled as inherited from the parent, and unchecked.
A child sequence length/item retrieval failure is reported and stops building that sequence. Keep already appended items; rebuild on the next menu opening.
At the top level visible/checked/separators/leaf commands are not evaluated; enabled propagates to children.
Child items may also contain no-argument callables returning child sequences. Evaluation occurs on the UI during menu creation/opening; exceptions are reported.
Selection receives a new application-registered CommandInfo (None before registration); command returns are ignored.
Only name (str) and items (the supplied reference, None if omitted) are readable/writable attributes. Others raise AttributeError.
The menu retains tree/callback references. setMenu(None) or window destruction detaches it and releases retained references; avoid reference cycles.

`ckit.TaskTrayIcon(title optional, lbuttondown_handler optional, lbuttonup_handler optional, rbuttondown_handler optional, rbuttonup_handler optional, lbuttondoubleclick_handler optional)` also accepts keywords.
title defaults to an empty tooltip, limited to 127 UTF-16 code units (two per supplementary character). Excess raises ValueError before OS operations.
Receiver-window creation failure raises OSError with the Windows error, releases retained handler references and skips notification-area registration.
Omit unused handlers. Each takes (x, y, mod), ignores its return and reports exceptions.
Current x/y values come from the notification message, not usable cursor coordinates; obtain pyauto.Input.getCursorPos() when needed.
Registration failures with a timeout or no error code retry at one-second intervals through the UI message loop.
Before retrying, NIM_MODIFY checks whether registration already succeeded. Construction and Explorer-restart handling do not wait for retries.
The message loop must run. Other registration errors or timer creation failure log a diagnostic and stop retrying; Explorer-restart notifications attempt registration again.
No OS-registration success indicator. Dropping a wrapper does not close it; call destroy.
destroy invalidates the wrapper before releasing owned handler, popup-command and wrapper references. Subsequent destroy/popupMenu calls raise ValueError.
Calling TaskTrayIcon.__init__ again on a live wrapper raises ValueError without changing existing resources. Reinitialization is allowed after destroy completes.

| Python signature | Contract |
|---|---|
| TaskTrayIcon.destroy() | Remove icon and receiver window and release owned references. Repeated calls raise ValueError |
| TaskTrayIcon.popupMenu(x, y, items) | Keywords accepted. Same items, screen pixels, command(info), None return and callback retention as Window.popupMenu. Reentry on the same icon raises ValueError before argument conversion, preserving the outer menu. Display again after completion, cancellation or an exception. Other icons are unrestricted |

## Line and initialization/diagnostics

`ckit.Line(s)` is a TextWidget line value; keyword s is accepted. Split one trailing CRLF/CR/LF from str.
Preserves NUL and supplementary characters. No methods; attributes below are readable/writable.
Direct string/cache changes do not notify a document; use TextWidget.modifyText for normal editing. Unknown attributes raise AttributeError.

| Attribute | Initial value and constraints |
|---|---|
| s | Body str without the trailing newline. Assignment performs no type/newline processing; keep a str |
| end | Separated newline or empty str. Assignment requires str; only its suffix determines CRLF/CR/LF/empty |
| ctx, tokens | Syntax cache references, initially None; retain arbitrary Python objects |
| bg | Initially 0; integer background number 0..3 (bool and int subclasses accepted) |
| bookmark | Initially 0; integer number/bit values 0..7 (bool and int subclasses accepted) |
| modified | Initially False; assignment requires strictly True/False |

Assigning bg/bookmark raises TypeError for non-int values, OverflowError for C long conversion overflow, and ValueError for other out-of-range values. Failure preserves all attributes, including other flags.

The following initialization/diagnostic functions are also re-exported. Normal custom.py code need not call them again.
All are positional-only and return None. Error is an exported exception type, not a uniform failure type for these operations.

| Python signature | Contract |
|---|---|
| ckit.registerWindowClass(prefix) | Register prefix str + WindowClass/TaskTrayWindowClass once before creating windows. Already done by the application. Failures such as duplicate registration raise OSError. Changes process-wide class names |
| ckit.registerCommandInfoConstructor(constructor) | Retain/replace the process-wide no-argument menu-info factory. The application has registered CommandInfo. None does not unregister |
| ckit.enableBlockDetector(report_func) | Only retain a process-wide no-argument report callback; does not start monitoring |
| ckit.setBlockDetector() | If a report callback is registered, install a Python profiler on the calling thread. Call report_func() after a gap over 1000ms between profile events; ignore return, report exceptions. Not a complete stall detector/runtime measurement; replaces other profilers. Stop on the same thread with sys.setprofile(None) |
@endcond
*/

static PyMethodDef ckit_funcs[] =
	{
		{"registerWindowClass", _registerWindowClass, METH_VARARGS, ""},
		{"registerCommandInfoConstructor", _registerCommandInfoConstructor, METH_VARARGS, ""},
		{"enableBlockDetector", _enableBlockDetector, METH_VARARGS, ""},
		{"setBlockDetector", _setBlockDetector, METH_VARARGS, ""},
		{NULL, NULL}};

// ----------------------------------------------------------------------------
//
// ----------------------------------------------------------------------------

static PyModuleDef ckitcore_module =
	{
		PyModuleDef_HEAD_INIT,
		MODULE_NAME,
		"ckitcore module.",
		-1,
		ckit_funcs,
		NULL, NULL, NULL, NULL};

PyMODINIT_FUNC PyInit_ckitcore(void)
{
	if (PyType_Ready(&Attribute_Type) < 0)
		return NULL;
	if (PyType_Ready(&Image_Type) < 0)
		return NULL;
	if (PyType_Ready(&Font_Type) < 0)
		return NULL;
	if (PyType_Ready(&ImagePlane_Type) < 0)
		return NULL;
	if (PyType_Ready(&TextPlane_Type) < 0)
		return NULL;
	if (PyType_Ready(&MenuNode_Type) < 0)
		return NULL;
	if (PyType_Ready(&Window_Type) < 0)
		return NULL;
	if (PyType_Ready(&TaskTrayIcon_Type) < 0)
		return NULL;
	if (PyType_Ready(&Line_Type) < 0)
		return NULL;

	PyObject *m, *d;

	m = PyModule_Create(&ckitcore_module);
	if (m == NULL)
		return NULL;

	Py_INCREF(&Attribute_Type);
	PyModule_AddObject(m, "Attribute", (PyObject *)&Attribute_Type);

	Py_INCREF(&Image_Type);
	PyModule_AddObject(m, "Image", (PyObject *)&Image_Type);

	Py_INCREF(&Font_Type);
	PyModule_AddObject(m, "Font", (PyObject *)&Font_Type);

	Py_INCREF(&ImagePlane_Type);
	PyModule_AddObject(m, "ImagePlane", (PyObject *)&ImagePlane_Type);

	Py_INCREF(&TextPlane_Type);
	PyModule_AddObject(m, "TextPlane", (PyObject *)&TextPlane_Type);

	Py_INCREF(&MenuNode_Type);
	PyModule_AddObject(m, "MenuNode", (PyObject *)&MenuNode_Type);

	Py_INCREF(&Window_Type);
	PyModule_AddObject(m, "Window", (PyObject *)&Window_Type);

	Py_INCREF(&TaskTrayIcon_Type);
	PyModule_AddObject(m, "TaskTrayIcon", (PyObject *)&TaskTrayIcon_Type);

	Py_INCREF(&Line_Type);
	PyModule_AddObject(m, "Line", (PyObject *)&Line_Type);

	Line_static_init();

	d = PyModule_GetDict(m);

	Error = PyErr_NewException(MODULE_NAME ".Error", NULL, NULL);
	PyDict_SetItemString(d, "Error", Error);

	if (PyErr_Occurred())
	{
		Py_FatalError("can't initialize module " MODULE_NAME);
	}

	return m;
}
