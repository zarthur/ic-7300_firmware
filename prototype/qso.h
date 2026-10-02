#ifndef IC7300_QSO_H
#define IC7300_QSO_H
#include <stdbool.h>
#include <stdint.h>

typedef enum { QSO_GRID, QSO_REPORT, QSO_RREPORT, QSO_RR73, QSO_73,
               QSO_COMPLETE, QSO_CANCELLED, QSO_EXHAUSTED } qso_state;
typedef struct {
    int64_t utc_ms;
    int64_t monotonic_ms;
    int64_t last_sync_monotonic_ms;
    int64_t uncertainty_ms;
    bool source_valid;
} qso_clock_sample;
typedef struct {
    char local[12], peer[12], grid[5];
    int report_db, parity, retry_limit, attempts;
    qso_state state;
    bool enabled, active, clock_seen, time_policy_set;
    int64_t max_time_age_ms, max_time_uncertainty_ms;
    int64_t last_slot, last_rx_slot, active_slot, last_utc_ms, last_mono_ms;
    int64_t last_sync_monotonic_ms, last_time_uncertainty_ms;
    uint32_t generation;
} qso_t;
typedef struct { char text[40]; int64_t start_utc_ms; uint32_t generation; } qso_tx;

/* Standard short callsigns and four-character locators only in this prototype.
 * report_db is operator-supplied; sync score is NOT a calibrated SNR estimate. */
bool qso_init(qso_t *, const char *local, const char *grid, const char *peer,
              int report_db, int parity, int retry_limit);
void qso_enable(qso_t *);
void qso_cancel(qso_t *);
/* No default time-quality budget is assumed. Configure before enable; values
 * must come from an explicit integration policy, not from these host tests. */
bool qso_set_time_policy(qso_t *, int64_t max_age_ms,
                         int64_t max_uncertainty_ms);
bool qso_receive(qso_t *, const char *message, int64_t rx_slot);
/* Poll frequently. A TX reservation is issued only in [slot+500,slot+600] ms.
 * It requires a valid source, bounded uncertainty, and a recent UTC sync.
 * UTC discontinuity >250 ms relative to monotonic time cancels the session. */
bool qso_tick(qso_t *, const qso_clock_sample *, qso_tx *);
bool qso_tx_valid_at(qso_t *, const qso_tx *, const qso_clock_sample *);
void qso_tx_finished(qso_t *, const qso_tx *, const qso_clock_sample *,
                     bool success);
#endif
