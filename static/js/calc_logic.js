/**
 * [블라인드 면적(회배) 계산기]
 * @param {number} widthMm  : 가로 (mm)
 * @param {number} heightMm : 세로 (mm)
 * @param {string} type     : 제품 종류 ('콤비', '우드', '자바라' 등)
 * @returns {number}        : 계산된 회배 (소수점 둘째자리)
 */
function calcBlindArea(widthMm, heightMm, type) {
    // 1. 높이 보정: 150cm(1500mm) 미만은 1500mm로 고정
    var calcH = heightMm;
    if (calcH < 1500) {
        calcH = 1500;
    }

    // 2. 회배 계산 (가로m * 세로m)
    // 1000 * 1000 = 1,000,000으로 나누면 제곱미터(㎡)
    var area = (widthMm * calcH) / 1000000;

    // 3. 소수점 둘째 자리까지 반올림 (JS 부동소수점 오차 보정)
    area = Math.round(area * 100) / 100;

    // 4. 제품별 최소 물량(기본 회배) 적용
    var minArea = 1.5; // 기본값 (우드, 알루미늄, 허니콤 등)

    if (type.indexOf("콤비") > -1 || type.indexOf("롤스크린") > -1) {
        minArea = 2.0;
    } 
    else if (type.indexOf("자바라") > -1 || type.indexOf("홀딩도어") > -1) {
        minArea = 3.0;
    }

    // 계산된 면적이 최소값보다 작으면 최소값 리턴
    if (area < minArea) {
        return minArea;
    }

    return area;
}

/**
 * [커튼 폭수 계산기]
 * @param {number} widthMm     : 창문 가로 (mm)
 * @param {number} rippleRatio : 주름 배수 (1.5, 2.0, 3.0 등)
 * @param {string} fabricType  : 원단 종류 ('대폭', '소폭' - 여기선 소폭 개념으로 통일)
 * @returns {number}           : 필요 폭수 (정수)
 */
function calcCurtainPok(widthMm, rippleRatio, fabricType) {
    // 사장님 지침: 대폭/소폭 구분 없이 '소폭' 개념으로 접근 (약 135~140cm 유효폭 가정)
    // 보통 소폭 원단 1폭을 55인치(약 140cm)로 보지만, 
    // 주름 잡고 겹치는 부분 고려해서 안전하게 유효폭 130~135cm 정도로 계산식 잡는 게 보통임.
    // 여기서는 계산의 기준이 되는 '1폭의 커버 너비' 상수를 정의해야 함.
    
    // [질문] 이 부분 1폭당 커버 cm를 얼마로 잡을까? 
    // 일단 일반적인 소폭 기준(유효 135cm)으로 잡아둘게. 나중에 수정 가능.
    var fabricEffectiveWidth = 1350; // mm 단위

    // 필요 원단 전체 길이
    var requiredWidth = widthMm * rippleRatio;

    // 폭수 계산 (무조건 올림 Math.ceil)
    var pok = Math.ceil(requiredWidth / fabricEffectiveWidth);

    return pok;
}