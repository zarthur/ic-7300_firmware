#include "ui_state.h"

bool ft8_ui_state_init(ft8_ui_state *state) {
    if(!state)return false;
    state->initialized=true;
    state->enabled=false;
    return true;
}

bool ft8_ui_state_reset(ft8_ui_state *state,ft8_station *station) {
    if(!state || !station || !state->initialized)return false;
    station_cancel(station);
    state->enabled=false;
    return true;
}

bool ft8_ui_dispatch(ft8_ui_state *state,ft8_station *station,
                     ft8_ui_action action) {
    if(!state || !station || !state->initialized)return false;
    if(action==FT8_UI_ACTION_CANCEL){
        station_cancel(station);
        state->enabled=false;
        return true;
    }
    if(action!=FT8_UI_ACTION_ENABLE)return false;

    qso_t *qso=&station->qso;
    if(station->tx_state==STATION_TX_ABORT_REQUESTED
       || ((station->tx_state==STATION_TX_ABORTED
            || station->tx_state==STATION_TX_FAILED)
           && !station->backend_flush_confirmed)){
        state->enabled=false;
        return false;
    }
    if(!qso->time_policy_set || qso->max_time_age_ms<0
       || qso->max_time_uncertainty_ms<0 || qso->state>=QSO_COMPLETE){
        state->enabled=false;
        return false;
    }
    if(state->enabled){
        if(qso->enabled)return true;
        state->enabled=false;
        return false;
    }

    qso_enable(qso);
    if(!qso->enabled)return false;
    state->enabled=true;
    return true;
}
