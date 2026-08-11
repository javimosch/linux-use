/* lu_helpers.h — the one C shim linux-use needs.
 *
 * machin's `string` FFI return ALIASES the C buffer; it does not copy. So a
 * helper that returns a shared static buffer is unsafe — the next call
 * clobbers every outstanding value. lu_cstr instead aliases the caller's own
 * (uniquely allocated) pointer, letting MFL copy it and then g_free the
 * original. No shared state, no leak.
 */
#pragma once

static inline const char *lu_cstr(const char *s) {
	return s ? s : "";
}

/* Authoritative length of a C string. MFL's len() on an FFI-aliased string
 * can return a stale value, so the copy length must come from C. */
static inline int lu_strlen(const char *s) {
	if (!s) return 0;
	int n = 0;
	while (s[n]) n++;
	return n;
}

/* ---- AtspiEvent field accessors -------------------------------------
 * Reading these by byte offset from MFL would mean hand-computing struct
 * layout (including a 24-byte GValue). Let the C compiler do it. */
#include <atspi/atspi.h>

static inline const char *lu_ev_type(AtspiEvent *e) { return e && e->type ? e->type : ""; }
static inline void *lu_ev_source(AtspiEvent *e) { return e ? e->source : 0; }
static inline int lu_ev_detail1(AtspiEvent *e) { return e ? e->detail1 : 0; }
static inline int lu_ev_detail2(AtspiEvent *e) { return e ? e->detail2 : 0; }
