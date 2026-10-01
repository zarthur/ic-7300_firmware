#include "station.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

typedef struct {
    size_t queued, drained;
} mock_audio_backend;

static qso_tx start_station(ft8_station *station) {
    memset(station,0,sizeof(*station));
    assert(qso_init(&station->qso,"K1ABC","FN42","W9XYZ",-10,0,2));
    qso_enable(&station->qso);
    assert(station_tick(station,500,500,1000));
    assert(station->tx_state==STATION_TX_GENERATING);
    return station->reservation;
}

static void mock_queue(ft8_station *station,const qso_tx *ticket,
                       mock_audio_backend *backend,size_t count) {
    backend->queued+=count;
    assert(station_backend_report(station,ticket,STATION_BACKEND_QUEUED,
                                  backend->queued));
}

static void mock_generate_and_queue(ft8_station *station,const qso_tx *ticket,
                                    mock_audio_backend *backend) {
    float output[4096];
    while(station->generated_samples<FT8_SIGNAL_SAMPLES){
        size_t n=station_audio(station,output,sizeof(output)/sizeof(output[0]));
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
    assert(station_backend_report(&station,&ticket,STATION_BACKEND_DRAINED,
                                  FT8_SIGNAL_SAMPLES));
    backend.drained=FT8_SIGNAL_SAMPLES;
    assert(station.tx_state==STATION_TX_DRAINED);
    assert(!station.qso.active);
    assert(station.qso.state==QSO_GRID);
    uint32_t generation=station.qso.generation;
    assert(!station_backend_report(&station,&ticket,STATION_BACKEND_DRAINED,
                                   FT8_SIGNAL_SAMPLES));
    assert(station.qso.generation==generation);
    assert(station.tx_state==STATION_TX_DRAINED);
}

static void test_abort_requires_backend_flush_when_samples_are_pending(void) {
    ft8_station station;mock_audio_backend backend={0};float output[512];
    qso_tx ticket=start_station(&station);
    assert(station_audio(&station,output,512)==512);
    mock_queue(&station,&ticket,&backend,512);
    station_cancel(&station);
    assert(station.tx_state==STATION_TX_ABORT_REQUESTED);
    assert(station.qso.state==QSO_CANCELLED);
    assert(!station.backend_flush_confirmed);
    assert(qso_init(&station.qso,"K1ABC","FN42","W9XYZ",-10,0,2));
    qso_enable(&station.qso);
    assert(!station_tick(&station,500,500,1000));
    assert(station_audio(&station,output,512)==0);
    assert(!station_backend_report(&station,&ticket,STATION_BACKEND_DRAINED,512));
    assert(station.tx_state==STATION_TX_ABORT_REQUESTED);
    assert(station_backend_report(&station,&ticket,STATION_BACKEND_ABORTED,0));
    assert(station.tx_state==STATION_TX_ABORTED);
    assert(!station.backend_flush_confirmed);
    assert(!station_tick(&station,500,500,1000));
    assert(station_backend_report(&station,&ticket,STATION_BACKEND_FLUSHED,0));
    assert(station.tx_state==STATION_TX_FLUSHED);
    assert(station.backend_flush_confirmed);
    assert(!station_backend_report(&station,&ticket,STATION_BACKEND_FLUSHED,0));
    assert(qso_init(&station.qso,"K1ABC","FN42","W9XYZ",-10,0,2));
    qso_enable(&station.qso);
    assert(station_tick(&station,500,500,1000));
}

static void test_backend_flush_is_an_abort_outcome(void) {
    ft8_station station;mock_audio_backend backend={0};float output[256];
    qso_tx ticket=start_station(&station);
    assert(station_audio(&station,output,256)==256);
    mock_queue(&station,&ticket,&backend,256);
    assert(station_backend_report(&station,&ticket,STATION_BACKEND_FLUSHED,0));
    assert(station.tx_state==STATION_TX_FLUSHED);
    assert(station.qso.state==QSO_CANCELLED);
    assert(station.backend_flush_confirmed);
    assert(!station_backend_report(&station,&ticket,STATION_BACKEND_DRAINED,256));
    assert(station.tx_state==STATION_TX_FLUSHED);
}

static void test_duplicate_and_out_of_order_queue_progress_fail_closed(void) {
    ft8_station station;mock_audio_backend backend={0};float output[512];
    qso_tx ticket=start_station(&station);
    assert(station_audio(&station,output,512)==512);
    mock_queue(&station,&ticket,&backend,512);
    assert(!station_backend_report(&station,&ticket,STATION_BACKEND_QUEUED,512));
    assert(station.tx_state==STATION_TX_GENERATING);
    assert(!station_backend_report(&station,&ticket,STATION_BACKEND_QUEUED,256));
    assert(station.tx_state==STATION_TX_FAILED);
    assert(station.qso.state==QSO_CANCELLED);
    assert(!station.backend_flush_confirmed);
    assert(!station_backend_report(&station,&ticket,STATION_BACKEND_DRAINED,512));
    assert(station.tx_state==STATION_TX_FAILED);
    assert(station_backend_report(&station,&ticket,STATION_BACKEND_FLUSHED,0));
    assert(station.tx_state==STATION_TX_FAILED);
    assert(station.backend_flush_confirmed);
}

static void test_drain_before_queue_fails_closed(void) {
    ft8_station station;qso_tx ticket=start_station(&station);
    assert(!station_backend_report(&station,&ticket,STATION_BACKEND_DRAINED,1));
    assert(station.tx_state==STATION_TX_FAILED);
    assert(station.qso.state==QSO_CANCELLED);
    assert(station.drained_samples==0);
    assert(!station_backend_report(&station,&ticket,STATION_BACKEND_DRAINED,
                                   FT8_SIGNAL_SAMPLES));
    assert(station.tx_state==STATION_TX_FAILED);
}

static void test_backend_failure_cannot_complete_qso(void) {
    ft8_station station;mock_audio_backend backend={0};float output[128];
    qso_tx ticket=start_station(&station);
    assert(station_audio(&station,output,128)==128);
    mock_queue(&station,&ticket,&backend,128);
    assert(station_backend_report(&station,&ticket,STATION_BACKEND_FAILED,0));
    assert(station.tx_state==STATION_TX_FAILED);
    assert(station.qso.state==QSO_CANCELLED);
    assert(station.qso.active==false);
    assert(!station.backend_flush_confirmed);
    assert(!station_backend_report(&station,&ticket,STATION_BACKEND_DRAINED,128));
    assert(qso_init(&station.qso,"K1ABC","FN42","W9XYZ",-10,0,2));
    qso_enable(&station.qso);
    assert(!station_tick(&station,500,500,1000));
    assert(station_backend_report(&station,&ticket,STATION_BACKEND_FLUSHED,0));
    assert(station.tx_state==STATION_TX_FAILED);
    assert(station.backend_flush_confirmed);
    assert(station_tick(&station,500,500,1000));
}

static void test_stale_ticket_fails_closed(void) {
    ft8_station station;qso_tx ticket=start_station(&station),stale=ticket;
    stale.generation++;
    assert(!station_backend_report(&station,&stale,STATION_BACKEND_DRAINED,
                                   FT8_SIGNAL_SAMPLES));
    assert(station.tx_state==STATION_TX_FAILED);
    assert(station.qso.state==QSO_CANCELLED);
}

int main(void) {
    test_queue_is_not_completion();
    test_abort_requires_backend_flush_when_samples_are_pending();
    test_backend_flush_is_an_abort_outcome();
    test_duplicate_and_out_of_order_queue_progress_fail_closed();
    test_drain_before_queue_fails_closed();
    test_backend_failure_cannot_complete_qso();
    test_stale_ticket_fails_closed();
    puts("station tests passed: queued vs drained, abort, flush, duplicate/out-of-order, failure, stale ticket");
    return 0;
}
