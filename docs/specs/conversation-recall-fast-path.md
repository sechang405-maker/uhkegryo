# 명백한 새 요청의 기억 분류 생략
## Why
새 레퍼런스 요청도 memory classify를 기다린다. classify 호출 수와 회상·후속 수정 회귀를 측정한다.
## Goal
명백한 새 시각 요청은 classify 0회다. 회상/애매한 입력은 기존 분류로 보낸다. 원본 조회와 인용 검증을 유지한다. 요약·모델 변경은 제외한다.
## What
새 요청을 빠르게 처리하되 키워드 없는 회상과 짧은 답을 놓치지 않는다. 기존 조건은 그대로 본문 해석에 전달한다.
## How
- backend의 결정적 함수로 판정한다. pending_question이 있거나 12자 미만이면 기존 classify를 호출한다.
- 과거/지시/회상/수정 단서(아까, 이전, 전에, 지난, 그때, 방금, 추천, 기억, 했, 였, 뭐, 무엇, 어떤, 그거, 그것, 똑같, 같은, 다시, 그대로, 유지, 바꿔, 변경, 말해, 알려, 앞서, 저번, 마지막, 첫, 결과, 사용한, 보낸, 선택한, 공백으로 구분된 이/그/저/해당, first/previous/earlier/remember/recommend*/suggest*/again/that/what/change/same/history) 또는 물음표가 있으면 기존 classify로 보낸다. 인용 안의 단서도 보수적으로 유지한다.
- 위 단서 없이 체형·자세·포즈·시점·원근·배치·캐릭터·레퍼런스·reference·pose·character·perspective 표현과 찾아/그려/보여/검색/find/draw/show/search 요청 동사가 함께 있으면 classify를 생략한다. 나머지는 기존 classify다.
- 회상 생략 시 (None, False)를 반환한다. session_context·원본 검증·conditions 갱신은 변경하지 않는다. 프롬프트 수정 없음.
## AC
- Given 이전 기록, When 명백한 새 시각 요청, Then classify 없이 해석하며 기존 조건을 전달한다.
- Given 이전 기록, When '아까 추천한 포즈는?' 또는 '추천했던 자세 이름은?', Then 기존 classify/원본 조회를 수행한다.
- Given 이전 확인 질문 또는 짧고 애매한 답, When 입력, Then 기존 classify와 맥락 전달을 유지한다.
- Given 후속 수정 또는 인용 속 과거 키워드, When 입력, Then 보수적으로 기존 classify를 사용한다.
