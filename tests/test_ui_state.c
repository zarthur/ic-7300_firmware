#include "ui_state.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

static void station_init(ft8_station *station,bool with_policy) {
    memset(station,0,sizeof(*station));
    assert(qso_init(&station->qso,"K1ABC","FN42","W9XYZ",-10,0,2));
    if(with_policy)assert(qso_set_time_policy(&station->qso,1000,20));
}

static void test_boot_defaults_and_uninitialized_rejection(void) {
    ft8_ui_state state={0};ft8_station station;station_init(&station,true);
    assert(!state.initialized && !state.enabled);
    assert(!ft8_ui_dispatch(&state,&station,FT8_UI_ACTION_ENABLE));
    assert(!station.qso.enabled);
    assert(ft8_ui_state_init(&state));
    assert(state.initialized && !state.enabled);
    assert(!station.qso.enabled && !station.qso.active);
    assert(station.tx_state==STATION_TX_IDLE);
}

static void test_enable_requires_configured_qso_time_policy(void) {
    ft8_ui_state state={0};ft8_station station;station_init(&station,false);
    assert(ft8_ui_state_init(&state));
    uint32_t generation=station.qso.generation;
    assert(!ft8_ui_dispatch(&state,&station,FT8_UI_ACTION_ENABLE));
    assert(!state.enabled && !station.qso.enabled);
    assert(station.qso.generation==generation);
    assert(station.tx_state==STATION_TX_IDLE && !station.qso.active);
}

static void test_enable_waits_for_backend_abort_flush(void) {
    ft8_ui_state state={0};ft8_station station;station_init(&station,true);
    assert(ft8_ui_state_init(&state));
    station.tx_state=STATION_TX_ABORT_REQUESTED;
    assert(!ft8_ui_dispatch(&state,&station,FT8_UI_ACTION_ENABLE));
    assert(!state.enabled && !station.qso.enabled);
    station.tx_state=STATION_TX_ABORTED;
    assert(!ft8_ui_dispatch(&state,&station,FT8_UI_ACTION_ENABLE));
    assert(!state.enabled && !station.qso.enabled);
    station.tx_state=STATION_TX_FAILED;
    assert(!ft8_ui_dispatch(&state,&station,FT8_UI_ACTION_ENABLE));
    assert(!state.enabled && !station.qso.enabled);
    station.tx_state=STATION_TX_IDLE;
    assert(ft8_ui_dispatch(&state,&station,FT8_UI_ACTION_ENABLE));
    assert(state.enabled && station.qso.enabled);
}

static void test_enable_and_repeated_enable_are_idempotent(void) {
    ft8_ui_state state={0};ft8_station station;station_init(&station,true);
    assert(ft8_ui_state_init(&state));
    assert(ft8_ui_dispatch(&state,&station,FT8_UI_ACTION_ENABLE));
    assert(state.enabled && station.qso.enabled);
    uint32_t generation=station.qso.generation;
    assert(ft8_ui_dispatch(&state,&station,FT8_UI_ACTION_ENABLE));
    assert(state.enabled && station.qso.enabled);
    assert(station.qso.generation==generation);
    assert(!station.qso.active && station.tx_state==STATION_TX_IDLE);
}

static void test_cancel_and_repeated_cancel_are_idempotent(void) {
    ft8_ui_state state={0};ft8_station station;station_init(&station,true);
    assert(ft8_ui_state_init(&state));
    assert(ft8_ui_dispatch(&state,&station,FT8_UI_ACTION_ENABLE));
    assert(ft8_ui_dispatch(&state,&station,FT8_UI_ACTION_CANCEL));
    assert(!state.enabled && !station.qso.enabled && !station.qso.active);
    assert(station.qso.state==QSO_CANCELLED);
    uint32_t generation=station.qso.generation;
    assert(ft8_ui_dispatch(&state,&station,FT8_UI_ACTION_CANCEL));
    assert(!state.enabled && station.qso.state==QSO_CANCELLED);
    assert(station.qso.generation==generation);
    assert(station.tx_state==STATION_TX_IDLE);
}

static void test_reset_cancels_and_restarts_at_disabled_default(void) {
    ft8_ui_state state={0};ft8_station station;station_init(&station,true);
    assert(ft8_ui_state_init(&state));
    assert(ft8_ui_dispatch(&state,&station,FT8_UI_ACTION_ENABLE));
    assert(ft8_ui_state_reset(&state,&station));
    assert(state.initialized && !state.enabled);
    assert(!station.qso.enabled && !station.qso.active);
    assert(station.qso.state==QSO_CANCELLED);
    uint32_t generation=station.qso.generation;
    assert(ft8_ui_state_reset(&state,&station));
    assert(!state.enabled && station.qso.generation==generation);
    assert(!ft8_ui_dispatch(&state,&station,FT8_UI_ACTION_ENABLE));
    assert(!state.enabled && !station.qso.enabled);
}

static void test_invalid_action_and_null_inputs_fail_without_enabling(void) {
    ft8_ui_state state={0};ft8_station station;station_init(&station,true);
    assert(ft8_ui_state_init(&state));
    assert(!ft8_ui_dispatch(&state,&station,(ft8_ui_action)99));
    assert(!state.enabled && !station.qso.enabled);
    assert(!ft8_ui_dispatch(NULL,&station,FT8_UI_ACTION_ENABLE));
    assert(!ft8_ui_dispatch(&state,NULL,FT8_UI_ACTION_ENABLE));
    assert(!ft8_ui_state_init(NULL));
    assert(!ft8_ui_state_reset(&state,NULL));
    assert(!state.enabled && !station.qso.enabled);
}

static void test_external_qso_invalidation_clears_ui_enable_state(void) {
    ft8_ui_state state={0};ft8_station station;station_init(&station,true);
    assert(ft8_ui_state_init(&state));
    assert(ft8_ui_dispatch(&state,&station,FT8_UI_ACTION_ENABLE));
    qso_cancel(&station.qso);
    assert(!ft8_ui_dispatch(&state,&station,FT8_UI_ACTION_ENABLE));
    assert(!state.enabled && !station.qso.enabled);
}

int main(void) {
    test_boot_defaults_and_uninitialized_rejection();
    test_enable_requires_configured_qso_time_policy();
    test_enable_waits_for_backend_abort_flush();
    test_enable_and_repeated_enable_are_idempotent();
    test_cancel_and_repeated_cancel_are_idempotent();
    test_reset_cancels_and_restarts_at_disabled_default();
    test_invalid_action_and_null_inputs_fail_without_enabling();
    test_external_qso_invalidation_clears_ui_enable_state();
    puts("UI state tests passed: RAM-only defaults, enable/cancel dispatch and failures");
    return 0;
}
