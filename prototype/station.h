#ifndef IC7300_STATION_H
#define IC7300_STATION_H
#include "codec.h"
#include "qso.h"

typedef enum {
    STATION_TX_IDLE,
    STATION_TX_GENERATING,
    STATION_TX_QUEUED,
    STATION_TX_DRAINED,
    STATION_TX_ABORT_REQUESTED,
    STATION_TX_ABORTED,
    STATION_TX_FLUSHED,
    STATION_TX_FAILED
} station_tx_state;

typedef enum {
    STATION_BACKEND_QUEUED,
    STATION_BACKEND_DRAINED,
    STATION_BACKEND_ABORTED,
    STATION_BACKEND_FLUSHED,
    STATION_BACKEND_FAILED
} station_backend_event;

typedef struct {
    qso_t qso;
    qso_tx reservation;
    ft8_tx waveform;
    station_tx_state tx_state;
    size_t generated_samples, queued_samples, drained_samples;
    bool backend_flush_confirmed;
} ft8_station;

/* Caller initializes qso, installs a time-quality policy, selects peer, and
 * explicitly enables transmission. Pass a current UTC/monotonic quality sample
 * to audio and backend-progress callbacks; expired or invalid quality
 * invalidates the ticket. All methods run on one serialized event loop; not
 * interrupt/thread safe.
 * This is a host-side contract only; no radio backend is implemented here. */
bool station_tick(ft8_station *,const qso_clock_sample *,float frequency_hz);
size_t station_audio(ft8_station *,const qso_clock_sample *,float *,size_t);
/* Invalidates local audio/QSO state; an active backend must still report abort
 * and, when needed, confirm its output queue was flushed. */
void station_cancel(ft8_station *);

/* QUEUED/DRAINED reports carry monotonic cumulative sample counts for this
 * reservation. QUEUED means accepted by a backend queue; DRAINED means the
 * backend reports those samples consumed. Only a complete drain finishes the
 * QSO. ABORTED, FLUSHED and FAILED require sample_count=0. FLUSHED confirms
 * discard of queued audio only; it says nothing about PTT or RF. Duplicate
 * progress returns false without state change; stale or out-of-order reports
 * cancel the reservation and fail closed. */
bool station_backend_report(ft8_station *,const qso_tx *,station_backend_event,
                            size_t cumulative_samples,const qso_clock_sample *);
#endif
