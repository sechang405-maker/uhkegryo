// Final user-approved fixed 3-D layout. Coordinates are the shared world-space
// mockup anchors; they are scaled and counter-rotated once so INITIAL_VIEW
// presents the same frontal composition while preserving real yaw/pitch depth.
// The mockup renderer applies a final 1.05 scene scale. Remove that presentation
// scale while mapping its approved 398.6-unit body radius into this camera.
export const APPROVED_LAYOUT_SCALE=.4/1.05;
// The perspective branch is translated as one rigid world-space group so its
// hub shares the body hub's projected height in INITIAL_VIEW. Keeping this in
// world Y (rather than changing raw camera-space Y) preserves every internal
// branch direction and length through rotation.
export const PERSPECTIVE_WORLD_Y_OFFSET=-198.62762577155928;

const RAW_APPROVED_LAYOUT=Object.freeze({
  'category:body':[-288.2775,-182.07,-242.76],
  'category:pose':[-84,0,220.5],
  'category:composition':[409.5,173.25,-136.5],
  'category:perspective':[262.5,357,299.25],
  'body_hourglass':[-390.508858,-374.032333,-507.684199],
  'body_inverted_triangle':[-257.96894,-398.573051,-448.128072],
  'body_triangle':[-396.353746,-399.918456,-298.593159],
  'body_slim':[-655.286491,-276.136015,-190.774952],
  'body_childlike':[-515.314384,-125.347984,-399.925253],
  'body_human_proportion':[-378.061976,-178.930342,-524.275407],
  'pose_contrapposto':[-418.34625,13.415914,537.692909],
  'pose_weight_shift':[-400.627243,-255.038999,376.914334],
  'pose_s_curve':[-214.273578,-273.718723,427.403309],
  'pose_standing':[-111.922673,-242.222569,527.25967],
  'pose_sitting':[-26.300193,-370.110523,545.037648],
  'pose_gesture':[23.086529,-153.299941,497.624984],
  'pose_reclining':[-25.093118,83.595969,515.21578],
  'pose_kneeling':[-104.693738,136.227448,630.584357],
  'pose_walking':[-75.437055,312.855353,591.957221],
  'pose_running':[-147.681984,228.497935,544.060994],
  'pose_jumping':[-239.310606,173.366947,478.4718],
  'pose_hand_open_palm':[-491.136401,73.696667,480.007662],
  'view_front':[470.713241,456.583526,132.39367],
  'view_three_quarter':[683.289667,-26.765465,-189.587907],
  'view_high_angle':[539.741982,-134.627188,-196.139894],
  'view_low_angle':[553.614195,-107.576222,-403.117665],
  'view_profile':[429.647731,-57.302444,-484.129562],
  'view_back':[362.240877,36.312585,-521.724999],
  'view_birds_eye':[385.441297,148.662651,-514.529507],
  'view_worms_eye':[303.207553,160.871258,-490.873995],
  'view_dutch_angle':[260.264194,381.875731,-370.82301],
  'view_over_the_shoulder':[351.461688,401.900329,-348.858962],
  'view_full_body':[328.122323,443.190477,-179.395372],
  'composition_rule_of_thirds':[395.920239,521.843201,-48.07169],
  'layout_composition':[433.053884,359.400229,150.386531],
  'perspective_three_point':[218.992845,491.193894,584.867671],
  'perspective_foreshortening':[323.466491,373.056973,572.401369],
  'perspective_vanishing_point':[556.255754,432.392667,450.803384],
  'perspective_one_point':[483.126418,526.575724,259.341384],
  'perspective_two_point':[290.629047,699.225727,466.973387],
  'pose_legs_crossed_at_knee':[-186.304602,-440.825967,702.664767],
  'pose_ankles_crossed':[-176.755074,-532.098672,687.202591],
  'pose_cross_legged_floor':[-101.785246,-741.343742,654.631412],
  'pose_action_two_hand_aiming':[-81.872418,-711.061456,753.492068],
  'pose_contrapposto_arm_raised':[-565.803121,-40.821392,568.145535],
  'pose_sitting_upright':[80.507386,-605.363547,695.223134],
  'pose_sitting_on_edge':[175.885759,-442.006097,804.690294],
  'pose_slouching':[47.883441,-520.711724,787.521278],
  'pose_sitting_leaning_forward':[54.565249,-423.576043,755.43182],
  'pose_sitting_leaning_back':[-28.781644,-445.121457,988.714453],
  'pose_lotus':[-3.757319,-330.328057,772.960574],
  'pose_half_lotus':[-128.160706,-381.772126,755.355637],
  'pose_seiza':[-10.539048,-645.25681,588.616013],
  'pose_contrapposto_classic':[-702.382408,-120.05854,747.244247],
  'pose_contrapposto_weight_shift':[-533.04782,-208.97255,762.721367],
  'pose_contrapposto_dynamic':[-461.702205,-64.775932,759.127101],
  'pose_contrapposto_s_curve':[-561.901185,49.447847,940.134136],
});

// The approved front view left the upper-right sector unused because the
// three longest perspective branches all pointed below their fixed hub.
// Rotate only those direct branches in camera-space XY. Their raw Z values,
// hub distance, straight edge lengths, and every unrelated anchor stay fixed.
const UPWARD_PERSPECTIVE_BRANCH_ROTATIONS=Object.freeze({
  perspective_vanishing_point:-45*Math.PI/180,
  perspective_one_point:-110*Math.PI/180,
  perspective_two_point:165*Math.PI/180,
});
const BODY_INWARD_SHIFT=.15;

function adjustedRawAnchor(id,anchor) {
  if(id==='category:body'||id.startsWith('body_')) {
    const hub=RAW_APPROVED_LAYOUT['category:body'];
    return [anchor[0]-hub[0]*BODY_INWARD_SHIFT,anchor[1]-hub[1]*BODY_INWARD_SHIFT,
      anchor[2]-hub[2]*BODY_INWARD_SHIFT];
  }
  const angle=UPWARD_PERSPECTIVE_BRANCH_ROTATIONS[id];
  if(angle===undefined) return anchor;
  const hub=RAW_APPROVED_LAYOUT['category:perspective'],dx=anchor[0]-hub[0],dy=anchor[1]-hub[1],
    cosine=Math.cos(angle),sine=Math.sin(angle);
  return [hub[0]+dx*cosine-dy*sine,hub[1]+dx*sine+dy*cosine,anchor[2]];
}

export function approvedCatalogWorldLayout(view) {
  const cosPitch=Math.cos(view.pitch),sinPitch=Math.sin(view.pitch),cosYaw=Math.cos(view.yaw),sinYaw=Math.sin(view.yaw);
  return new Map(Object.entries(RAW_APPROVED_LAYOUT).map(([id,anchor])=>{
    const [rawX,rawY,rawZ]=adjustedRawAnchor(id,anchor);
    const cameraX=rawX*APPROVED_LAYOUT_SCALE,cameraY=rawY*APPROVED_LAYOUT_SCALE,depth=rawZ*APPROVED_LAYOUT_SCALE,
      worldYOffset=id==='category:perspective'||id.startsWith('perspective_')?PERSPECTIVE_WORLD_Y_OFFSET:0,
      worldY=cameraY*cosPitch+depth*sinPitch+worldYOffset,yawZ=-cameraY*sinPitch+depth*cosPitch,
      worldX=cameraX*cosYaw-yawZ*sinYaw,worldZ=cameraX*sinYaw+yawZ*cosYaw;
    return [id,Object.freeze({x:worldX,y:worldY,z:worldZ})];
  }));
}
