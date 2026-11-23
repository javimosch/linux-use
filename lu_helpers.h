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

/* Resident set size in kB, or 0 if unavailable. machin's read_file() returns
 * empty for procfs (zero-length stat), so this has to be done in C. */
static inline int lu_rss_kb(void) {
	FILE *f = fopen("/proc/self/statm", "r");
	if (!f) return 0;
	long total = 0, resident = 0;
	int n = fscanf(f, "%ld %ld", &total, &resident);
	fclose(f);
	if (n != 2) return 0;
	long page_kb = 4096 / 1024;
	return (int)(resident * page_kb);
}

/* ---- localhost WebSocket / HTTP client (CDP) ------------------------
 * Blocking, one request in flight, localhost only. Exists because machin
 * has no socket FFI. Responses are heap strings — consume with takestr.
 */
#include <sys/socket.h>
#include <netdb.h>
#include <unistd.h>

static int lu_tcp(const char *host, int port) {
	char ps[16];
	snprintf(ps, sizeof(ps), "%d", port);
	struct addrinfo hints = {0}, *res = NULL;
	hints.ai_family = AF_INET;
	hints.ai_socktype = SOCK_STREAM;
	if (getaddrinfo(host, ps, &hints, &res) != 0 || !res) return -1;
	int fd = socket(res->ai_family, res->ai_socktype, res->ai_protocol);
	if (fd < 0 || connect(fd, res->ai_addr, res->ai_addrlen) < 0) {
		if (fd >= 0) close(fd);
		fd = -1;
	}
	freeaddrinfo(res);
	return fd;
}

static int lu_write_all(int fd, const char *p, long n) {
	while (n > 0) {
		long w = send(fd, p, n, 0);
		if (w <= 0) return -1;
		p += w;
		n -= w;
	}
	return 0;
}

static long lu_read_all(int fd, char *p, long n) {
	long got = 0;
	while (got < n) {
		long r = recv(fd, p + got, n - got, 0);
		if (r <= 0) return r <= 0 && got == 0 ? r : got;
		got += r;
	}
	return got;
}

/* GET http://host:port/path — returns the body (heap, takestr) or NULL. */
static inline char *lu_http_get(const char *host, int port, const char *path) {
	int fd = lu_tcp(host, port);
	if (fd < 0) return NULL;
	char req[1024];
	snprintf(req, sizeof(req), "GET %s HTTP/1.1\r\nHost: %s:%d\r\nConnection: close\r\n\r\n", path, host, port);
	if (lu_write_all(fd, req, (long)strlen(req)) < 0) { close(fd); return NULL; }
	/* DevTools answers HTTP/1.1 but may keep the socket open anyway — stop
	 * at Content-Length rather than waiting for EOF. */
	long cap = 1 << 20, n = 0, want = -1;
	char *buf = g_malloc(cap + 1);
	for (;;) {
		if (n == cap) { cap *= 2; buf = g_realloc(buf, cap + 1); }
		long r = recv(fd, buf + n, cap - n, 0);
		if (r <= 0) break;
		n += r;
		buf[n] = 0;
		if (want < 0) {
			char *he = strstr(buf, "\r\n\r\n");
			if (he) {
				char *cl = strcasestr(buf, "Content-Length:");
				if (cl && cl < he) {
					want = (he + 4 - buf) + atol(cl + 15);
				} else {
					want = n; /* no length: take what arrived */
				}
			}
		}
		if (want >= 0 && n >= want) break;
	}
	close(fd);
	buf[n] = 0;
	char *body = strstr(buf, "\r\n\r\n");
	if (!body) { g_free(buf); return NULL; }
	return g_strdup(body + 4);
}

/* ws://host:port/path -> fd, -1 on failure. Static handshake key: any
 * value is legal, the server echoes the derived accept hash. */
static inline int lu_ws_open(const char *url) {
	char host[128] = {0}, path[256] = "/";
	int port = 0;
	if (strncmp(url, "ws://", 5) != 0) return -1;
	const char *hp = url + 5;
	const char *sl = strchr(hp, '/');
	const char *co = sl ? sl : url + strlen(url);
	if (sscanf(hp, "%127[^:/]", host) != 1) return -1;
	const char *pp = memchr(hp, ':', co - hp);
	if (pp) port = atoi(pp + 1);
	if (sl) snprintf(path, sizeof(path), "%s", sl);
	if (port <= 0) return -1;
	int fd = lu_tcp(host, port);
	if (fd < 0) return -1;
	char req[1024];
	snprintf(req, sizeof(req),
		"GET %s HTTP/1.1\r\nHost: %s:%d\r\nUpgrade: websocket\r\n"
		"Connection: Upgrade\r\nSec-WebSocket-Key: bGludXgtdXNlLWNkcA==\r\n"
		"Sec-WebSocket-Version: 13\r\n\r\n", path, host, port);
	if (lu_write_all(fd, req, (long)strlen(req)) < 0) { close(fd); return -1; }
	char hdr[4096] = {0};
	long n = 0;
	while (n < (long)sizeof(hdr) - 1 && !strstr(hdr, "\r\n\r\n")) {
		long r = recv(fd, hdr + n, sizeof(hdr) - 1 - n, 0);
		if (r <= 0) { close(fd); return -1; }
		n += r;
		hdr[n] = 0;
	}
	if (!strstr(hdr, " 101")) { close(fd); return -1; }
	return fd;
}

static int lu_ws_send_frame(int fd, const char *msg) {
	unsigned long n = strlen(msg);
	unsigned char hdr[14];
	long hi = 0;
	hdr[hi++] = 0x81; /* FIN + text */
	if (n < 126) hdr[hi++] = 0x80 | (unsigned char)n;
	else if (n < 65536) { hdr[hi++] = 0x80 | 126; hdr[hi++] = n >> 8; hdr[hi++] = n; }
	else { hdr[hi++] = 0x80 | 127; for (int i = 7; i >= 0; i--) hdr[hi++] = (n >> (8 * i)) & 0xff; }
	unsigned char mask[4] = {0x6c, 0x75, 0x77, 0x73};
	memcpy(hdr + hi, mask, 4);
	hi += 4;
	if (lu_write_all(fd, (char *)hdr, hi) < 0) return -1;
	/* Mask in chunks — no second copy of a possibly-huge message. */
	unsigned long off = 0;
	while (off < n) {
		unsigned char chunk[8192];
		unsigned long c = n - off > sizeof(chunk) ? sizeof(chunk) : n - off;
		for (unsigned long i = 0; i < c; i++) chunk[i] = msg[off + i] ^ mask[(off + i) & 3];
		if (lu_write_all(fd, (char *)chunk, (long)c) < 0) return -1;
		off += c;
	}
	return 0;
}

/* Read frames until one complete TEXT message accumulates (continuations
 * joined). Returns heap string, NULL on close/error. Pings get a pong. */
static char *lu_ws_recv_msg(int fd) {
	long cap = 1 << 20, n = 0;
	char *buf = g_malloc(cap + 1);
	for (;;) {
		unsigned char h[2];
		if (lu_read_all(fd, (char *)h, 2) != 2) { g_free(buf); return NULL; }
		int fin = h[0] & 0x80, op = h[0] & 0x0f;
		unsigned long ln = h[1] & 0x7f;
		if (ln == 126) { unsigned char e[2]; if (lu_read_all(fd, (char *)e, 2) != 2) { g_free(buf); return NULL; } ln = (e[0] << 8) | e[1]; }
		else if (ln == 127) { unsigned char e[8]; if (lu_read_all(fd, (char *)e, 8) != 8) { g_free(buf); return NULL; } ln = 0; for (int i = 0; i < 8; i++) ln = (ln << 8) | e[i]; }
		if (h[1] & 0x80) { unsigned char m[4]; lu_read_all(fd, (char *)m, 4); }
		if (n + (long)ln > cap) { while (n + (long)ln > cap) cap *= 2; buf = g_realloc(buf, cap + 1); }
		if (lu_read_all(fd, buf + n, (long)ln) != (long)ln) { g_free(buf); return NULL; }
		n += (long)ln;
		if (op == 9) { unsigned char pong[2] = {0x8a, 0x80}; unsigned char mk[4] = {0x6c,0x75,0x77,0x73}; lu_write_all(fd, (char *)pong, 2); lu_write_all(fd, (char *)mk, 4); n = 0; continue; }
		if (op == 8) { g_free(buf); return NULL; }
		if (fin) { buf[n] = 0; return buf; }
	}
}

/* Send msg, return the first received message that carries "id": — our
 * response (CDP events have no id field). Heap string or NULL. */
static inline char *lu_ws_call(int fd, const char *msg) {
	if (lu_ws_send_frame(fd, msg) < 0) return NULL;
	for (int tries = 0; tries < 64; tries++) {
		char *m = lu_ws_recv_msg(fd);
		if (!m) return NULL;
		if (strstr(m, "\"id\":")) return m;
		g_free(m);
	}
	return NULL;
}

static inline void lu_ws_close(int fd) { if (fd >= 0) close(fd); }
