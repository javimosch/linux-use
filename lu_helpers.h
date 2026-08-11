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

/* ---- AtspiCollection ------------------------------------------------
 * Server-side matching: ONE D-Bus round trip returns every node matching a
 * role/state rule, instead of walking the tree and querying each node. The
 * GArray/GHashTable/AtspiMatchRule plumbing lives here so MFL never has to
 * model GLib containers. */

static inline GArray *lu_roles_new(void) {
	return g_array_new(FALSE, FALSE, sizeof(AtspiRole));
}

static inline void lu_roles_add(GArray *a, int role) {
	AtspiRole r = (AtspiRole)role;
	g_array_append_val(a, r);
}

/* AtspiRole for a role NAME ("push button"), or -1. at-spi exposes
 * role->name but no name->role, so scan the enum. */
static inline int lu_role_from_name(const char *want) {
	if (!want || !*want) return -1;
	for (int i = 0; i <= ATSPI_ROLE_LAST_DEFINED; i++) {
		char *n = atspi_role_get_name((AtspiRole)i);
		if (!n) continue;
		int hit = (g_strcmp0(n, want) == 0);
		g_free(n);
		if (hit) return i;
	}
	return -1;
}

/* Match rule: any of `roles`, and (if showing) ATSPI_STATE_SHOWING. */
static inline AtspiMatchRule *lu_rule_new(GArray *roles, int showing) {
	AtspiStateSet *ss = atspi_state_set_new(NULL);
	if (showing) atspi_state_set_add(ss, ATSPI_STATE_SHOWING);
	/* An EMPTY criteria set with MATCH_ANY matches NOTHING ("any of zero" is
	 * false), while MATCH_ALL over an empty set is vacuously true. So every
	 * unused criterion must be MATCH_ALL; only the roles list uses ANY. */
	AtspiMatchRule *r = atspi_match_rule_new(
		ss, ATSPI_Collection_MATCH_ALL,
		NULL, ATSPI_Collection_MATCH_ALL,
		roles, ATSPI_Collection_MATCH_ANY,
		NULL, ATSPI_Collection_MATCH_ALL,
		FALSE);
	g_object_unref(ss);
	return r;
}

static inline GArray *lu_matches(AtspiAccessible *root, AtspiMatchRule *rule, int count) {
	AtspiCollection *c = atspi_accessible_get_collection_iface(root);
	if (!c) return NULL;
	GArray *g = atspi_collection_get_matches(
		c, rule, ATSPI_Collection_SORT_ORDER_CANONICAL, count, TRUE, NULL);
	g_object_unref(c);
	return g;
}

static inline int lu_arr_len(GArray *a) { return a ? (int)a->len : 0; }

/* Borrowed pointer — the GArray still owns the reference. */
static inline void *lu_arr_get(GArray *a, int i) {
	if (!a || i < 0 || i >= (int)a->len) return 0;
	return g_array_index(a, AtspiAccessible *, i);
}

static inline void lu_arr_free(GArray *a) {
	if (!a) return;
	for (guint i = 0; i < a->len; i++) {
		AtspiAccessible *o = g_array_index(a, AtspiAccessible *, i);
		if (o) g_object_unref(o);
	}
	g_array_free(a, TRUE);
}

static inline void lu_rule_free(AtspiMatchRule *r) { if (r) g_object_unref(r); }
static inline void lu_roles_free(GArray *a) { if (a) g_array_free(a, TRUE); }

static inline int lu_role_count(void) { return ATSPI_ROLE_LAST_DEFINED; }
