import test from 'node:test';
import assert from 'node:assert/strict';
import { resizeComposerInput, createScrollEndAnchor } from '../lib/composer-autosize.mjs';

function fixture(contentHeight=44) {
 const input={value:'text',offsetWidth:300,scrollHeight:contentHeight,scrollTop:0,clientHeight:44,style:{height:'44px'}};
 return input;
}
test('one line shrinks back after a large paste',()=>{
 const input=fixture(500);
 resizeComposerInput(input,{viewportHeight:900});assert.equal(input.style.height,'164px');assert.equal(input.style.overflowY,'auto');
 input.scrollHeight=44;resizeComposerInput(input,{viewportHeight:900});assert.equal(input.style.height,'44px');assert.equal(input.style.overflowY,'hidden');
});
test('small visible viewport caps input but guarantees one line',()=>{
 const input=fixture(500);
 resizeComposerInput(input,{viewportHeight:400});assert.equal(input.style.height,'100px');
 resizeComposerInput(input,{viewportHeight:100});assert.equal(input.style.height,'44px');
});
test('empty input ignores a wrapped placeholder after reload or resize',()=>{
 const input=fixture(68);input.value='';resizeComposerInput(input,{viewportHeight:500});
 assert.equal(input.style.height,'44px');assert.equal(input.style.overflowY,'hidden');
});
test('width reflow can grow and shrink without changing content',()=>{
 const input=fixture(68);resizeComposerInput(input,{viewportHeight:900});assert.equal(input.style.height,'68px');
 input.scrollHeight=116;resizeComposerInput(input,{viewportHeight:900});assert.equal(input.style.height,'116px');
 input.scrollHeight=68;resizeComposerInput(input,{viewportHeight:900});assert.equal(input.style.height,'68px');
});
test('hidden mobile input keeps its height until shown',()=>{
 const input=fixture(0);input.offsetWidth=0;resizeComposerInput(input,{viewportHeight:900});assert.deepEqual(input.style,{height:'44px'});
});
for(const atEnd of [true,false])test('resize '+(atEnd?'keeps end readers at end':'preserves older message position'),()=>{
 const input=fixture(300),scroll={scrollHeight:1000,scrollTop:atEnd?444:100,get clientHeight(){return 600-parseFloat(input.style.height);}};
 resizeComposerInput(input,{viewportHeight:900,scrollContainer:scroll});assert.equal(scroll.scrollTop,atEnd?564:100);
});
test('focus/footer or viewport resize follows the state before layout changed',()=>{
 const scroll={scrollHeight:1000,clientHeight:500,scrollTop:500},anchor=createScrollEndAnchor(scroll);
 scroll.clientHeight=450;anchor.onResize();assert.equal(scroll.scrollTop,550);
 scroll.scrollTop=200;anchor.onScroll();scroll.clientHeight=400;anchor.onResize();assert.equal(scroll.scrollTop,200);
 scroll.scrollTop=600;anchor.onScroll();scroll.clientHeight=350;anchor.onResize();assert.equal(scroll.scrollTop,650);
});
