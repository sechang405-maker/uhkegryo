const TURN_RADIANS=Math.PI*2;
const TURN_DURATION_MS=120000;
const MAX_FRAME_DELTA_MS=100;

export function createAutoRotationState() {
  return {lastTime:null,stopped:false};
}

export function advanceAutoRotation(state,now,enabled) {
  if(state.stopped) return {state:{...state,lastTime:now},deltaYaw:0};
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

export function stopAutoRotation(state) {
  return {...state,stopped:true,lastTime:null};
}

export function manualRotationStarted(pointerCount,distance) {
  return pointerCount>=2||distance>=5;
}
