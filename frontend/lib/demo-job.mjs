import { HOME_TERMS } from "./home-catalog.mjs";

export const uiDemoEnabled = process.env.NODE_ENV === "development"
  && process.env.NEXT_PUBLIC_UI_DEMO === "1";

export const DEMO_REQUEST_TEXT = "어깨와 골반 폭이 비슷하고 허리가 들어간 캐릭터를 그리고 싶어요.";

// UI 레이아웃 확인용 더미 Pin 결과입니다. 실제 검색·저장 경로에는 사용하지 않습니다.
const DEMO_PINS = [
  ["43558321392566658", "https://i.pinimg.com/564x/57/99/f7/5799f724a2a753afcded64591c3e509d.jpg"],
  ["7599893117398382", "https://i.pinimg.com/564x/c2/55/9f/c2559f1363a57e070365fb6ec0b9d744.jpg"],
  ["633387444697956", "https://i.pinimg.com/564x/fa/83/23/fa8323a99c3119d3fa159c7527ef440a.jpg"],
  ["29766047533423483", "https://i.pinimg.com/564x/be/a4/71/bea47196f3af98195e5e98a51bee2f2c.jpg"],
  ["27373510232415990", "https://i.pinimg.com/564x/2d/97/17/2d97170804194a8c61e470178b126d3f.jpg"],
  ["165999936258067590", "https://i.pinimg.com/564x/2b/2e/83/2b2e83e12af3de9709d7b9c79805b906.jpg"],
  ["42150946509590731", "https://i.pinimg.com/564x/d6/2a/b2/d62ab22f17aa0088510b15a9cdfc6942.jpg"],
  ["33636328462713574", "https://i.pinimg.com/564x/45/d3/e1/45d3e127b848d06f5f4e884700ce7959.jpg"],
].map(([pin_id, thumbnail_url]) => ({
  pin_id,
  pin_url: `https://www.pinterest.com/pin/${pin_id}/`,
  thumbnail_url,
  status: "available",
}));

export const DEMO_JOB = {
  job_status: "completed",
  result: {
    agent_status: "success",
    answer_text: "예시 캐릭터의 ‘어깨와 골반 폭이 비슷하고 허리가 들어간 체형’은 모래시계형으로 설명할 수 있습니다.\n\n포즈와 시점은 체형과 별개의 조건입니다. 한쪽 다리에 체중을 싣는 자세를 원한다면 콘트라포스토를, 정면에서 보이는 모습을 원한다면 정면 시점을 참고할 수 있습니다. 이것들은 아직 사용자가 지정한 조건이 아니라 탐색 예시입니다.\n\n왼쪽 카테고리에서 레퍼런스를 둘러보고, 바꾸고 싶은 부분을 아래에 이어서 적어 보세요.",
    reference_plan: {
      terms: HOME_TERMS.map((term) => ({ ...term, pins: DEMO_PINS })),
    },
  },
};
