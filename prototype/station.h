#ifndef IC7300_STATION_H
#define IC7300_STATION_H
#include "codec.h"
#include "qso.h"
typedef struct {qso_t qso; qso_tx reservation; ft8_tx waveform;} ft8_station;
/* Caller initializes qso, selects peer, and explicitly enables transmission.
 * All methods run on one serialized event loop; not interrupt/thread safe. */
bool station_tick(ft8_station *,int64_t utc_ms,int64_t monotonic_ms,float frequency_hz);
size_t station_audio(ft8_station *,float *,size_t);
void station_cancel(ft8_station *);
#endif
