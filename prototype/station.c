#include "station.h"
bool station_tick(ft8_station *s,int64_t utc,int64_t mono,float hz){
    if(!qso_tick(&s->qso,utc,mono,&s->reservation))return false;
    if(!ft8_tx_init(&s->waveform,s->reservation.text,hz)){qso_cancel(&s->qso);return false;}
    return true;
}
size_t station_audio(ft8_station *s,float *output,size_t count){
    /* Validate on every chunk: cancellation/clock changes invalidate queued PCM. */
    if(!qso_tx_valid(&s->qso,&s->reservation)){ft8_tx_cancel(&s->waveform);return 0;}
    return ft8_tx_pull(&s->waveform,output,count);
}
void station_cancel(ft8_station *s){qso_cancel(&s->qso);ft8_tx_cancel(&s->waveform);}
