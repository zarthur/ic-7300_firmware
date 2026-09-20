#ifndef IC7300_QSO_H
#define IC7300_QSO_H
#include <stdbool.h>
#include <stdint.h>

typedef enum { QSO_GRID, QSO_REPORT, QSO_RREPORT, QSO_RR73, QSO_73,
               QSO_COMPLETE, QSO_CANCELLED, QSO_EXHAUSTED } qso_state;
typedef struct {
    char local[12], peer[12], grid[5];
    int report_db, parity, retry_limit, attempts;
    qso_state state;
    bool enabled, active, clock_seen;
    int64_t last_slot, last_rx_slot, active_slot, last_utc_ms, last_mono_ms;
    uint32_t generation;
} qso_t;
typedef struct { char text[40]; int64_t start_utc_ms; uint32_t generation; } qso_tx;

/* Standard short callsigns and four-character locators only in this prototype.
 * report_db is operator-supplied; sync score is NOT a calibrated SNR estimate. */
bool qso_init(qso_t *, const char *local, const char *grid, const char *peer,
              int report_db, int parity, int retry_limit);
void qso_enable(qso_t *);
void qso_cancel(qso_t *);
bool qso_receive(qso_t *, const char *message, int64_t rx_slot);
/* Poll frequently. A TX reservation is issued only in [slot+500,slot+600] ms.
 * UTC discontinuity >250 ms relative to monotonic time cancels the session. */
bool qso_tick(qso_t *, int64_t utc_ms, int64_t monotonic_ms, qso_tx *);
bool qso_tx_valid(const qso_t *, const qso_tx *);
void qso_tx_finished(qso_t *, const qso_tx *, bool success);
#endif
