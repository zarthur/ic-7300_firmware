#include "station.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

typedef struct {
    size_t queued, drained;
} mock_audio_backend;

static qso_clock_sample sample_at(int64_t utc,int64_t mono,int64_t sync,
                                  int64_t uncertainty,bool valid) {
    qso_clock_sample sample={utc,mono,sync,uncertainty,valid};return sample;
}
static void init_qso(qso_t *q) {
    assert(qso_init(q,"K1ABC","FN42","W9XYZ",-10,0,2));
    assert(qso_set_time_policy(q,1000,20));
    qso_enable(q);
}
static bool tick_fresh(ft8_station *station,int64_t utc,int64_t mono) {
    qso_clock_sample sample=sample_at(utc,mono,mono,0,true);
    return station_tick(station,&sample,1000);
}
static qso_clock_sample current_sample(const ft8_station *station) {
    return sample_at(station->qso.last_utc_ms,station->qso.last_mono_ms,
                     station->qso.last_sync_monotonic_ms,
                     station->qso.last_time_uncertainty_ms,true);
}
static size_t audio_latest(ft8_station *station,float *output,size_t count) {
    qso_clock_sample sample=current_sample(station);
    return station_audio(station,&sample,output,count);
}
static bool backend_latest(ft8_station *station,const qso_tx *ticket,
                           station_backend_event event,size_t count) {
    qso_clock_sample sample=current_sample(station);
    return station_backend_report(station,ticket,event,count,&sample);
}

static qso_tx start_station(ft8_station *station) {
    memset(station,0,sizeof(*station));
    init_qso(&station->qso);
    assert(tick_fresh(station,500,500));
    assert(station->tx_state==STATION_TX_GENERATING);
    return station->reservation;
}

static void mock_queue(ft8_station *station,const qso_tx *ticket,
                       mock_audio_backend *backend,size_t count) {
    backend->queued+=count;
    assert(backend_latest(station,ticket,STATION_BACKEND_QUEUED,
                                  backend->queued));
}

static void mock_generate_and_queue(ft8_station *station,const qso_tx *ticket,
                                    mock_audio_backend *backend) {
    float output[4096];
    while(station->generated_samples<FT8_SIGNAL_SAMPLES){
        size_t n=audio_latest(station,output,sizeof(output)/sizeof(output[0]));
        assert(n>0);
        mock_queue(station,ticket,backend,n);
    }
    assert(backend->queued==FT8_SIGNAL_SAMPLES);
}

static void test_queue_is_not_completion(void) {
    ft8_station station;mock_audio_backend backend={0};
    qso_tx ticket=start_station(&station);
    mock_generate_and_queue(&station,&ticket,&backend);
    assert(station.tx_state==STATION_TX_QUEUED);
    assert(station.qso.active);
    assert(station.qso.state==QSO_GRID);
    assert(station.drained_samples==0);
    assert(backend_latest(&station,&ticket,STATION_BACKEND_DRAINED,
                                  FT8_SIGNAL_SAMPLES));
    backend.drained=FT8_SIGNAL_SAMPLES;
    assert(station.tx_state==STATION_TX_DRAINED);
    assert(!station.qso.active);
    assert(station.qso.state==QSO_GRID);
    uint32_t generation=station.qso.generation;
    assert(!backend_latest(&station,&ticket,STATION_BACKEND_DRAINED,
                                   FT8_SIGNAL_SAMPLES));
    assert(station.qso.generation==generation);
    assert(station.tx_state==STATION_TX_DRAINED);
}

static void test_abort_requires_backend_flush_when_samples_are_pending(void) {
    ft8_station station;mock_audio_backend backend={0};float output[512];
    qso_tx ticket=start_station(&station);
    assert(audio_latest(&station,output,512)==512);
    mock_queue(&station,&ticket,&backend,512);
    station_cancel(&station);
    assert(station.tx_state==STATION_TX_ABORT_REQUESTED);
    assert(station.qso.state==QSO_CANCELLED);
    assert(!station.backend_flush_confirmed);
    init_qso(&station.qso);
    assert(!tick_fresh(&station,500,500));
    assert(audio_latest(&station,output,512)==0);
    assert(!backend_latest(&station,&ticket,STATION_BACKEND_DRAINED,512));
    assert(station.tx_state==STATION_TX_ABORT_REQUESTED);
    assert(backend_latest(&station,&ticket,STATION_BACKEND_ABORTED,0));
    assert(station.tx_state==STATION_TX_ABORTED);
    assert(!station.backend_flush_confirmed);
    assert(!tick_fresh(&station,500,500));
    assert(backend_latest(&station,&ticket,STATION_BACKEND_FLUSHED,0));
    assert(station.tx_state==STATION_TX_FLUSHED);
    assert(station.backend_flush_confirmed);
    assert(!backend_latest(&station,&ticket,STATION_BACKEND_FLUSHED,0));
    init_qso(&station.qso);
    assert(tick_fresh(&station,500,500));
}

static void test_backend_flush_is_an_abort_outcome(void) {
    ft8_station station;mock_audio_backend backend={0};float output[256];
    qso_tx ticket=start_station(&station);
    assert(audio_latest(&station,output,256)==256);
    mock_queue(&station,&ticket,&backend,256);
    assert(backend_latest(&station,&ticket,STATION_BACKEND_FLUSHED,0));
    assert(station.tx_state==STATION_TX_FLUSHED);
    assert(station.qso.state==QSO_CANCELLED);
    assert(station.backend_flush_confirmed);
    assert(!backend_latest(&station,&ticket,STATION_BACKEND_DRAINED,256));
    assert(station.tx_state==STATION_TX_FLUSHED);
}

static void test_duplicate_and_out_of_order_queue_progress_fail_closed(void) {
    ft8_station station;mock_audio_backend backend={0};float output[512];
    qso_tx ticket=start_station(&station);
    assert(audio_latest(&station,output,512)==512);
    mock_queue(&station,&ticket,&backend,512);
    assert(!backend_latest(&station,&ticket,STATION_BACKEND_QUEUED,512));
    assert(station.tx_state==STATION_TX_GENERATING);
    assert(!backend_latest(&station,&ticket,STATION_BACKEND_QUEUED,256));
    assert(station.tx_state==STATION_TX_FAILED);
    assert(station.qso.state==QSO_CANCELLED);
    assert(!station.backend_flush_confirmed);
    assert(!backend_latest(&station,&ticket,STATION_BACKEND_DRAINED,512));
    assert(station.tx_state==STATION_TX_FAILED);
    assert(backend_latest(&station,&ticket,STATION_BACKEND_FLUSHED,0));
    assert(station.tx_state==STATION_TX_FAILED);
    assert(station.backend_flush_confirmed);
}

static void test_drain_before_queue_fails_closed(void) {
    ft8_station station;qso_tx ticket=start_station(&station);
    assert(!backend_latest(&station,&ticket,STATION_BACKEND_DRAINED,1));
    assert(station.tx_state==STATION_TX_FAILED);
    assert(station.qso.state==QSO_CANCELLED);
    assert(station.drained_samples==0);
    assert(!backend_latest(&station,&ticket,STATION_BACKEND_DRAINED,
                                   FT8_SIGNAL_SAMPLES));
    assert(station.tx_state==STATION_TX_FAILED);
}

static void test_backend_failure_cannot_complete_qso(void) {
    ft8_station station;mock_audio_backend backend={0};float output[128];
    qso_tx ticket=start_station(&station);
    assert(audio_latest(&station,output,128)==128);
    mock_queue(&station,&ticket,&backend,128);
    assert(backend_latest(&station,&ticket,STATION_BACKEND_FAILED,0));
    assert(station.tx_state==STATION_TX_FAILED);
    assert(station.qso.state==QSO_CANCELLED);
    assert(station.qso.active==false);
    assert(!station.backend_flush_confirmed);
    assert(!backend_latest(&station,&ticket,STATION_BACKEND_DRAINED,128));
    init_qso(&station.qso);
    assert(!tick_fresh(&station,500,500));
    assert(backend_latest(&station,&ticket,STATION_BACKEND_FLUSHED,0));
    assert(station.tx_state==STATION_TX_FAILED);
    assert(station.backend_flush_confirmed);
    assert(tick_fresh(&station,500,500));
}

static void test_stale_ticket_fails_closed(void) {
    ft8_station station;qso_tx ticket=start_station(&station),stale=ticket;
    stale.generation++;
    assert(!backend_latest(&station,&stale,STATION_BACKEND_DRAINED,
                                   FT8_SIGNAL_SAMPLES));
    assert(station.tx_state==STATION_TX_FAILED);
    assert(station.qso.state==QSO_CANCELLED);
}

static void test_stale_quality_stops_generation_and_requests_backend_abort(void) {
    ft8_station station;float output[128];
    qso_tx ticket=start_station(&station);
    qso_clock_sample stale=sample_at(1501,1501,500,0,true);
    assert(station_audio(&station,&stale,output,128)==0); /* 1001 ms since sync */
    assert(station.tx_state==STATION_TX_ABORT_REQUESTED);
    assert(station.qso.state==QSO_CANCELLED);
    assert(backend_latest(&station,&ticket,STATION_BACKEND_ABORTED,0));
    assert(backend_latest(&station,&ticket,STATION_BACKEND_FLUSHED,0));
    assert(station.tx_state==STATION_TX_FLUSHED);
    assert(station.backend_flush_confirmed);

    ticket=start_station(&station);
    qso_clock_sample current=current_sample(&station);
    assert(station_audio(&station,&current,output,128)==128);
    assert(!station_backend_report(&station,&ticket,STATION_BACKEND_QUEUED,
                                   128,&stale));
    assert(station.tx_state==STATION_TX_ABORT_REQUESTED);
    assert(backend_latest(&station,&ticket,STATION_BACKEND_ABORTED,0));
    assert(backend_latest(&station,&ticket,STATION_BACKEND_FLUSHED,0));
}

int main(void) {
    test_queue_is_not_completion();
    test_abort_requires_backend_flush_when_samples_are_pending();
    test_backend_flush_is_an_abort_outcome();
    test_duplicate_and_out_of_order_queue_progress_fail_closed();
    test_drain_before_queue_fails_closed();
    test_backend_failure_cannot_complete_qso();
    test_stale_ticket_fails_closed();
    test_stale_quality_stops_generation_and_requests_backend_abort();
    puts("station tests passed: backend lifecycle and stale time-quality abort");
    return 0;
}
