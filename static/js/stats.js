/* stats.js - Python API 연동 버전 */
let myChart = null;
const currentYear = new Date().getFullYear();
let globalData = null; // 전역 데이터 저장

document.addEventListener("DOMContentLoaded", function() {
    initZoomControl(); // 줌 기능

    const select = document.getElementById('yearSelect');
    if(select) {
        // 최근 5년 옵션 생성
        for (let i = 0; i < 5; i++) {
            let y = currentYear - i;
            let opt = document.createElement('option');
            opt.value = y;
            opt.innerText = y + "년";
            select.appendChild(opt);
        }

        select.addEventListener('change', function() {
            loadData(this.value);
        });

        // 초기 로드
        loadData(currentYear);
    }
});

const statsCache = new Map();

/* -----------------------------------------------------------
   [API] 데이터 로드
   ----------------------------------------------------------- */
async function loadData(year) {
    // 1. 캐시 확인
    if (statsCache.has(year)) {
        processStatsData(statsCache.get(year), year);
        loadList(year, 0); // 캐시가 있어도 리스트는 최신화 가능성 있으므로 별도 로드
        return;
    }

    try {
        // [변경 이유] 요약 데이터와 상세 리스트를 병렬(Parallel)로 호출하여 전체 로딩 시간 단축
        const [statsRes, listRes] = await Promise.all([
            fetch(`/api/stats/data?year=${year}`),
            fetch(`/api/stats/list?year=${year}&month=0`)
        ]);

        const data = await statsRes.json();
        const listHtml = await listRes.text();

        // 2. 데이터 처리 및 캐싱
        globalData = data;
        statsCache.set(year, data);
        processStatsData(data, year);

        // 3. 리스트 즉시 반영
        document.getElementById('orderList').innerHTML = listHtml;
        
    } catch (error) {
        console.error("데이터 로드 실패:", error);
    }
}

function processStatsData(data, year) {
    updateSummary(data.summary, true);
    renderChart(data, year);
}

function loadList(year, month) {
    let url = `/api/stats/list?year=${year}`;
    if(month > 0) url += `&month=${month}`;

    const label = document.getElementById('filterLabel');
    if(month > 0) {
        label.innerText = `🔍 ${month}월 내역`;
        label.style.display = 'inline-block';
        document.getElementById('btnReset').style.display = 'inline-block';
    } else {
        label.style.display = 'none';
    }

    fetch(url)
    .then(res => res.text()) // HTML 조각 수신
    .then(html => {
        document.getElementById('orderList').innerHTML = html;
    })
    .catch(err => console.error(err));
}

function resetView() {
    const year = document.getElementById('yearSelect').value;
    if(globalData) {
        updateSummary(globalData.summary, true); 
    }
    loadList(year, 0); 
    
    document.getElementById('btnReset').style.display = 'none';
    document.getElementById('filterLabel').style.display = 'none';
}

function updateSummary(data, isTotal) {
    const fmt = (num) => num.toLocaleString();
    
    document.getElementById('lblCnt').innerText = isTotal ? "총 완료 건수" : "월 완료 건수";
    document.getElementById('lblRev').innerText = isTotal ? "총 매출액" : "월 매출액";

    document.getElementById('totalCnt').innerText = fmt(data.total_cnt) + " 건";
    document.getElementById('totalRev').innerText = fmt(data.total_rev) + " 원";

    const catBox = document.getElementById('catBox');
    if (isTotal) {
        catBox.style.opacity = '1';
        document.getElementById('cntCurtain').innerText = fmt(data.cat_c);
        document.getElementById('cntBlind').innerText = fmt(data.cat_b);
        document.getElementById('cntEtc').innerText = fmt(data.cat_e);
    } else {
        catBox.style.opacity = '0.3'; 
    }
}

/* -----------------------------------------------------------
   차트 렌더링 (Chart.js)
   ----------------------------------------------------------- */
function renderChart(data, years) {
    const ctx = document.getElementById('salesChart').getContext('2d');
    if (myChart) myChart.destroy();

    const datasets = [];

    // [1] 선택 년도 매출 (막대)
    datasets.push({
        type: 'bar',
        label: `${years.sel}년 금액`,
        data: data.data_selected.amt,
        backgroundColor: '#4e73df',
        borderRadius: 4,
        order: 2,
        yAxisID: 'y'
    });

    // [2] 선택 년도 건수 (선)
    datasets.push({
        type: 'line',
        label: `${years.sel}년 건수`,
        data: data.data_selected.cnt,
        borderColor: '#e74a3b', 
        backgroundColor: '#e74a3b',
        borderWidth: 2,
        pointRadius: 4,
        pointBackgroundColor: '#fff',
        pointBorderWidth: 2,
        tension: 0.3,
        order: 0,
        yAxisID: 'y1'
    });

    // [3] 비교 년도 (다음해) - 과거 조회 시 미래 비교
    if (years.next < years.cur) {
        datasets.push({
            type: 'bar',
            label: `${years.next}년 금액`,
            data: data.data_next.amt,
            backgroundColor: '#858796',
            borderRadius: 4,
            order: 3,
            yAxisID: 'y'
        });
    }

    // [4] 올해 (현재 진행상황 비교용)
    if (parseInt(years.sel) !== parseInt(years.cur)) {
        datasets.push({
            type: 'bar',
            label: `${years.cur}년 금액`,
            data: data.data_current.amt,
            backgroundColor: 'rgba(28, 200, 138, 0.5)',
            borderColor: '#1cc88a',
            borderWidth: 1,
            borderRadius: 4,
            order: 2,
            yAxisID: 'y'
        });
    }

    myChart = new Chart(ctx, {
        data: {
            labels: ['1월','2월','3월','4월','5월','6월','7월','8월','9월','10월','11월','12월'],
            datasets: datasets
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            plugins: {
                tooltip: {
                    callbacks: {
                        label: function(ctx) {
                            let label = ctx.dataset.label || '';
                            let val = ctx.raw;
                            if (label.includes('금액')) return label + ': ' + val.toLocaleString() + '원';
                            if (label.includes('건수')) return label + ': ' + val + '건';
                            return label + ': ' + val;
                        }
                    }
                }
            },
            scales: {
                y: {
                    type: 'linear', display: true, position: 'left', beginAtZero: true,
                    ticks: { callback: (val) => val.toLocaleString() }
                },
                y1: {
                    type: 'linear', display: true, position: 'right', beginAtZero: true,
                    grid: { drawOnChartArea: false }, ticks: { stepSize: 1 }
                },
                x: { grid: { display: false } }
            },
            // [차트 클릭 이벤트]
            onClick: (e, elements) => {
                if (elements.length > 0) {
                    const index = elements[0].index; 
                    const month = index + 1;
                    const year = document.getElementById('yearSelect').value;
                    
                    // 클릭한 달의 요약 정보 업데이트 (로컬 데이터 활용)
                    const monthAmt = globalData.data_selected.amt[index];
                    const monthCnt = globalData.data_selected.cnt[index];
                    
                    const monthSummary = {
                        total_cnt: monthCnt, total_rev: monthAmt,
                        cat_c: 0, cat_b: 0, cat_e: 0 // 월별 카테고리는 현재 집계 안함
                    };
                    updateSummary(monthSummary, false);
                    
                    // 상세 리스트 새로고침
                    loadList(year, month);
                }
            }
        }
    });
}

function initZoomControl() {
    const ZOOM_STEP = 2; const MIN_SIZE = 12; const MAX_SIZE = 34;
    const htmlRoot = document.documentElement;
    const btnIn = document.getElementById('btn-zoom-in');
    const btnOut = document.getElementById('btn-zoom-out');
    const btnReset = document.getElementById('btn-zoom-reset');

    const getDefaultSize = () => window.innerWidth >= 1200 ? 14 : 16;
    const getCurrentSize = () => parseFloat(window.getComputedStyle(htmlRoot).fontSize);
    const updateFontSize = (type) => {
        let newSize = getCurrentSize();
        if (type === 'plus') newSize += ZOOM_STEP;
        else if (type === 'minus') newSize -= ZOOM_STEP;
        else newSize = getDefaultSize();
        if (newSize < MIN_SIZE) newSize = MIN_SIZE;
        if (newSize > MAX_SIZE) newSize = MAX_SIZE;
        htmlRoot.style.fontSize = `${newSize}px`;
    };

    if (btnIn) btnIn.addEventListener('click', () => updateFontSize('plus'));
    if (btnOut) btnOut.addEventListener('click', () => updateFontSize('minus'));
    if (btnReset) btnReset.addEventListener('click', () => updateFontSize('reset'));
}