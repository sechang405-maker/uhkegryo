import test from 'node:test';
import assert from 'node:assert/strict';
import { usableGalleryPins } from '../lib/gallery-pins.mjs';
test('unusable images disappear, healthy pins survive, IDs and image URLs deduplicate',()=>{
 const good=id=>({pin_id:id,status:'available',thumbnail_url:`https://i.pinimg.com/${id}.jpg`});
 const pins=[good('1'),good('1'),{...good('2'),thumbnail_url:good('1').thumbnail_url},good('3'),{pin_id:'4',status:'deleted'},...Array.from({length:10},(_,i)=>good(String(i+5)))];
 const result=usableGalleryPins(pins,{'card:3':true},'card');
 assert.equal(result.length,8);
 assert.equal(result[0].pin_id,'1');
 assert.ok(!result.some(pin=>['2','3','4'].includes(pin.pin_id)));
});
