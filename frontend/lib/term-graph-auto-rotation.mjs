const TURN_RADIANS=Math.PI*2;
const TURN_DURATION_MS=120000;
const MAX_FRAME_DELTA_MS=100;
const MANUAL_RESUME_DELAY_MS=10000;

export function createAutoRotationState() {
  return {lastTime:null,manualActive:false,resumeAt:null};
}

export function advanceAutoRotation(state,now,enabled) {
  if(state.manualActive) return {state:{...state,lastTime:now},deltaYaw:0};
  if(state.resumeAt!==null) {
    if(now<state.resumeAt) return {state:{...state,lastTime:now},deltaYaw:0};
    return {state:{...state,resumeAt:null,lastTime:now},deltaYaw:0};
  }
  if(!enabled||state.lastTime===null) return {state:{...state,lastTime:now},deltaYaw:0};
  const elapsed=Math.max(0,Math.min(MAX_FRAME_DELTA_MS,now-state.lastTime));
  return {
    state:{...state,lastTime:now},
    deltaYaw:TURN_RADIANS*elapsed/TURN_DURATION_MS,
  };
}

export function pauseAutoRotation(state,now) {
  return {...state,lastTime:now};
}

export function advanceGraphViewAutoRotation(view,state,now,enabled) {
  const advanced=advanceAutoRotation(state,now,enabled);
  return {
    state:advanced.state,
    view:advanced.deltaYaw ? {...view,yaw:view.yaw+advanced.deltaYaw} : view,
  };
}

export function beginManualRotation(state) {
  return {...state,manualActive:true,resumeAt:null,lastTime:null};
}

export function finishManualRotation(state,now) {
  if(!state.manualActive) return state;
  return {...state,manualActive:false,resumeAt:now+MANUAL_RESUME_DELAY_MS,lastTime:now};
}

export function manualRotationStarted(pointerCount,distance) {
  return pointerCount>=2||distance>=5;
}
