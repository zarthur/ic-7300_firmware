#include "station.h"
#include <string.h>

static bool output_active(const ft8_station *s) {
    return s->tx_state==STATION_TX_GENERATING || s->tx_state==STATION_TX_QUEUED;
}

static bool ticket_matches(const qso_tx *a,const qso_tx *b) {
    return a && b && a->generation==b->generation && a->start_utc_ms==b->start_utc_ms
        && !strncmp(a->text,b->text,sizeof(a->text));
}

static void invalidate_qso(ft8_station *s) {
    if (s->qso.state!=QSO_COMPLETE && s->qso.state!=QSO_CANCELLED
        && s->qso.state!=QSO_EXHAUSTED) qso_cancel(&s->qso);
    s->qso.active=false;
    s->qso.enabled=false;
}

static void request_abort(ft8_station *s) {
    invalidate_qso(s);
    ft8_tx_cancel(&s->waveform);
    s->tx_state=STATION_TX_ABORT_REQUESTED;
    s->backend_flush_confirmed=false;
}

static void fail_closed(ft8_station *s) {
    invalidate_qso(s);
    ft8_tx_cancel(&s->waveform);
    s->tx_state=STATION_TX_FAILED;
    s->backend_flush_confirmed=false;
}

bool station_tick(ft8_station *s,const qso_clock_sample *clock,float hz){
    if(!s)return false;
    if (s->tx_state==STATION_TX_ABORT_REQUESTED
        || ((s->tx_state==STATION_TX_ABORTED || s->tx_state==STATION_TX_FAILED)
            && !s->backend_flush_confirmed)) return false;
    bool was_output_active=output_active(s);
    if(!qso_tick(&s->qso,clock,&s->reservation)){
        if(was_output_active && !qso_tx_valid_at(&s->qso,&s->reservation,clock))request_abort(s);
        return false;
    }
    s->generated_samples=s->queued_samples=s->drained_samples=0;
    s->backend_flush_confirmed=false;
    s->tx_state=STATION_TX_GENERATING;
    if(!ft8_tx_init(&s->waveform,s->reservation.text,hz)){
        fail_closed(s);
        s->backend_flush_confirmed=true; /* no samples were handed to a backend */
        return false;
    }
    return true;
}

size_t station_audio(ft8_station *s,const qso_clock_sample *clock,
                     float *output,size_t count){
    if(!s || !output || !count || s->tx_state!=STATION_TX_GENERATING)return 0;
    /* Validate on every chunk: cancellation/clock changes invalidate generated PCM. */
    if(!qso_tx_valid_at(&s->qso,&s->reservation,clock)){request_abort(s);return 0;}
    if(s->generated_samples>=FT8_SIGNAL_SAMPLES)return 0;
    size_t n=ft8_tx_pull(&s->waveform,output,count);
    if(n>FT8_SIGNAL_SAMPLES-s->generated_samples){fail_closed(s);return 0;}
    s->generated_samples+=n;
    if(!n && s->generated_samples<FT8_SIGNAL_SAMPLES){fail_closed(s);return 0;}
    return n;
}

void station_cancel(ft8_station *s){
    if(!s)return;
    if(output_active(s)){request_abort(s);return;}
    invalidate_qso(s);
    ft8_tx_cancel(&s->waveform);
}

bool station_backend_report(ft8_station *s,const qso_tx *ticket,
                            station_backend_event event,size_t samples,
                            const qso_clock_sample *clock){
    if(!s || !ticket)return false;
    if(!ticket_matches(ticket,&s->reservation)){
        if(output_active(s))fail_closed(s);
        return false;
    }
    if(event<STATION_BACKEND_QUEUED || event>STATION_BACKEND_FAILED){
        if(output_active(s) || s->tx_state==STATION_TX_ABORT_REQUESTED)fail_closed(s);
        return false;
    }
    if(event==STATION_BACKEND_ABORTED || event==STATION_BACKEND_FLUSHED
       || event==STATION_BACKEND_FAILED){
        if(samples!=0){
            if(output_active(s) || s->tx_state==STATION_TX_ABORT_REQUESTED)fail_closed(s);
            return false;
        }
        if(event==STATION_BACKEND_ABORTED){
            if(!output_active(s) && s->tx_state!=STATION_TX_ABORT_REQUESTED)return false;
            invalidate_qso(s);
            ft8_tx_cancel(&s->waveform);
            s->tx_state=STATION_TX_ABORTED;
            s->backend_flush_confirmed=s->queued_samples==s->drained_samples;
            return true;
        }
        if(event==STATION_BACKEND_FLUSHED){
            if(s->tx_state==STATION_TX_DRAINED || s->tx_state==STATION_TX_IDLE
               || s->tx_state==STATION_TX_FLUSHED)return false;
            if(s->tx_state==STATION_TX_FAILED){
                if(s->backend_flush_confirmed)return false;
                s->backend_flush_confirmed=true;
                return true;
            }
            invalidate_qso(s);
            ft8_tx_cancel(&s->waveform);
            s->tx_state=STATION_TX_FLUSHED;
            s->backend_flush_confirmed=true;
            return true;
        }
        if(!output_active(s) && s->tx_state!=STATION_TX_ABORT_REQUESTED
           && s->tx_state!=STATION_TX_ABORTED)return false;
        fail_closed(s);
        return true;
    }

    if(s->tx_state==STATION_TX_DRAINED || s->tx_state==STATION_TX_ABORT_REQUESTED
       || s->tx_state==STATION_TX_ABORTED || s->tx_state==STATION_TX_FLUSHED
       || s->tx_state==STATION_TX_FAILED)return false;
    if(!qso_tx_valid_at(&s->qso,&s->reservation,clock)){
        request_abort(s);
        return false;
    }
    if(event==STATION_BACKEND_QUEUED){
        if(samples==s->queued_samples)return false; /* duplicate progress */
        if(samples<s->queued_samples || samples>s->generated_samples
           || samples>FT8_SIGNAL_SAMPLES){fail_closed(s);return false;}
        s->queued_samples=samples;
        if(s->generated_samples==FT8_SIGNAL_SAMPLES
           && s->queued_samples==FT8_SIGNAL_SAMPLES)s->tx_state=STATION_TX_QUEUED;
        return true;
    }
    if(event==STATION_BACKEND_DRAINED){
        if(samples==s->drained_samples)return false; /* duplicate progress */
        if(samples<s->drained_samples || samples>s->queued_samples
           || samples>FT8_SIGNAL_SAMPLES){fail_closed(s);return false;}
        if(samples==FT8_SIGNAL_SAMPLES){
            if(s->tx_state!=STATION_TX_QUEUED
               || s->generated_samples!=FT8_SIGNAL_SAMPLES
               || s->queued_samples!=FT8_SIGNAL_SAMPLES){fail_closed(s);return false;}
            s->drained_samples=samples;
            qso_tx_finished(&s->qso,&s->reservation,clock,true);
            s->tx_state=STATION_TX_DRAINED;
            return true;
        }
        s->drained_samples=samples;
        return true;
    }
    fail_closed(s);
    return false;
}
