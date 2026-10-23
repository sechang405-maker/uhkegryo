import test from 'node:test';
import assert from 'node:assert/strict';
import {
  advanceAutoRotation,
  advanceGraphViewAutoRotation,
  beginManualRotation,
  createAutoRotationState,
  finishManualRotation,
  manualRotationStarted,
  pauseAutoRotation,
} from '../lib/term-graph-auto-rotation.mjs';

test('frame-time integration completes one turn in 120 seconds',()=>{
  let state=createAutoRotationState(),yaw=0;
  ({state}=advanceAutoRotation(state,0,true));
  for(let now=16;now<=120000;now+=16) {
    const step=advanceAutoRotation(state,now,true);
    state=step.state;yaw+=step.deltaYaw;
  }
  assert.ok(Math.abs(yaw-Math.PI*2)<1e-9);
});

test('irregular frame times use elapsed time while a large jump is bounded',()=>{
  let state=createAutoRotationState(),yaw=0;
  ({state}=advanceAutoRotation(state,0,true));
  for(const now of [10,43,87]) {
    const step=advanceAutoRotation(state,now,true);
    state=step.state;yaw+=step.deltaYaw;
  }
  assert.ok(Math.abs(yaw-(Math.PI*2*87/120000))<1e-12);
  const jump=advanceAutoRotation(state,10087,true);
  assert.ok(Math.abs(jump.deltaYaw-(Math.PI*2*100/120000))<1e-12);
});

test('pause discards hidden time and reduced motion produces no rotation',()=>{
  let state=createAutoRotationState();
  ({state}=advanceAutoRotation(state,20,true));
  state=pauseAutoRotation(state,5000);
  const hidden=advanceAutoRotation(state,5100,false);
  assert.equal(hidden.deltaYaw,0);
  const resumed=advanceAutoRotation(hidden.state,5116,true);
  assert.ok(Math.abs(resumed.deltaYaw-(Math.PI*2*16/120000))<1e-12);
});

test('manual rotation resumes from the current angle after ten quiet seconds',()=>{
  let state=createAutoRotationState();
  ({state}=advanceAutoRotation(state,0,true));
  const beforeDrag=advanceAutoRotation(state,16,true);
  state=beginManualRotation(beforeDrag.state);
  state=finishManualRotation(state,1000);
  for(const now of [10999,11000]) {
    const step=advanceAutoRotation(state,now,true);
    state=step.state;
    assert.equal(step.deltaYaw,0);
  }
  const resumed=advanceAutoRotation(state,11016,true);
  assert.ok(Math.abs(resumed.deltaYaw-(Math.PI*2*16/120000))<1e-12);
});

test('another manual rotation resets the ten second wait',()=>{
  let state=finishManualRotation(beginManualRotation(createAutoRotationState()),1000);
  state=beginManualRotation(state);
  state=finishManualRotation(state,9000);
  assert.equal(advanceAutoRotation(state,18999,true).deltaYaw,0);
  const boundary=advanceAutoRotation(state,19000,true);
  assert.equal(boundary.deltaYaw,0);
  assert.ok(advanceAutoRotation(boundary.state,19016,true).deltaYaw>0);
});

test('holding a drag prevents timer based resumption',()=>{
  let state=finishManualRotation(beginManualRotation(createAutoRotationState()),0);
  state=beginManualRotation(state);
  for(const now of [10000,30000]) {
    const step=advanceAutoRotation(state,now,true);
    state=step.state;
    assert.equal(step.deltaYaw,0);
    assert.equal(state.manualActive,true);
  }
});

test('ordinary clicks keep rotation but mouse drag and touch gestures stop it',()=>{
  assert.equal(manualRotationStarted(1,4.99),false);
  assert.equal(manualRotationStarted(1,5),true);
  assert.equal(manualRotationStarted(2,0),true);
});

test('graph view integration changes only yaw and preserves pitch and zoom',()=>{
  let state=createAutoRotationState();
  let first=advanceGraphViewAutoRotation({yaw:.5,pitch:.2,zoom:.9},state,100,true);
  const second=advanceGraphViewAutoRotation(first.view,first.state,116,true);
  assert.ok(second.view.yaw>.5);
  assert.equal(second.view.pitch,.2);
  assert.equal(second.view.zoom,.9);
  const stopped=advanceGraphViewAutoRotation(second.view,beginManualRotation(second.state),132,true);
  assert.deepEqual(stopped.view,second.view);
});
