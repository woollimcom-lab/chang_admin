// 폼을 열고 모드(추가/수정)에 따라 설정을 변경하는 함수
function openForm(mode, orderID) {
    document.getElementById('formContainer').classList.add('active');
    const selectElement = document.getElementById('ProgressStatus');
    const selectElement1 = document.getElementById('PaymentStatus');

    if (mode === 'add') {
        document.getElementById('formTitle').innerText = '추가';
        clearForm();
        selectElement.disabled = false; // 추가 폼에서는 활성화
        selectElement1.disabled = false; // 추가 폼에서는 활성화
    } else if (mode === 'edit') {
        document.getElementById('formTitle').innerText = '수정';
        loadData(orderID, function () {
            // 데이터 로드 완료 후 ProgressStatus 비활성화
            selectElement.disabled = true;
            selectElement1.disabled = true;
        });
    }
}

// 폼의 모든 입력 필드를 초기화하고 기본값을 설정하는 함수
function clearForm() {
    var inputs = document.querySelectorAll('#dataForm input');
    for (var i = 0; i < inputs.length; i++) {
        inputs[i].value = '';
    }

    const selectFields = {
        ProgressStatus: '상담',
        PaymentStatus: '미입금',
        PaymentMethod: ''
    };

    for (const [id, defaultValue] of Object.entries(selectFields)) {
        document.getElementById(id).value = defaultValue;
    }

    const today = new Date();
    document.getElementById('ContractDate').value = today.toISOString().substring(0, 10);

    document.getElementById('ProgressStatus').disabled = false; // 초기 상태 활성화
}

// 데이터베이스에서 주문 데이터를 가져와 폼에 채우는 함수
function loadData(orderID, callback) {
    var xhr = new XMLHttpRequest();
    xhr.open('GET', 'cb.asp?action=load&id=' + orderID, true);

    xhr.onreadystatechange = function () {
        if (xhr.readyState === 4 && xhr.status === 200) {
            var data = JSON.parse(xhr.responseText);

            document.getElementById('OrderID').value = data.OrderID;
            document.getElementById('ContractDate').value = data.ContractDate;
            document.getElementById('CustomerName').value = data.CustomerName;
            document.getElementById('PhoneNumber').value = data.PhoneNumber;
            document.getElementById('Address').value = data.Address;
            document.getElementById('ProgressStatus').value = data.ProgressStatus;
            document.getElementById('PaymentStatus').value = data.PaymentStatus;
            document.getElementById('PaymentMethod').value = data.PaymentMethod;
            document.getElementById('BankName').value = data.BankName;
            document.getElementById('DepositorName').value = data.DepositorName;
            document.getElementById('ConstructionDate').value = data.ConstructionDate;
            document.getElementById('Cost').value = data.Cost;

            if (callback && typeof callback === "function") {
                callback();
            }
        }
    };

    xhr.send();
}

// 폼을 닫고 화면에서 숨기는 함수
function closeForm() {
    document.getElementById('formContainer').classList.remove('active');
}

// 업로드된 이미지를 미리보기 위해 파일을 읽는 함수
function previewImage(event) {
    var file = event.target.files[0];
    if (file) {
        var reader = new FileReader();
        reader.readAsDataURL(file);
    }
}

// 이미지 소스를 받아 사진 모달을 여는 함수
function showPhoto(imageSrc) {
    if (imageSrc) {
        document.getElementById('photoModalImg').src = imageSrc;
        document.getElementById('photoModal').classList.add('active');
        // document.getElementById('overlay').classList.add('active');
    }
}

// 사진 모달을 닫고 오버레이를 비활성화하는 함수
function closePhoto() {
    document.getElementById('photoModal').classList.remove('active');
    document.getElementById('overlay').classList.remove('active');
}

// 주문 삭제 여부를 확인하고 삭제를 실행하는 함수
function confirmDelete(orderID) {
    if (confirm("정말 삭제하시겠습니까?")) {
        location.href = 'cb.asp?action=delete&id=' + orderID;
    }
}

// 폼 제출 전 필수 입력값을 검증하는 함수
function validateForm(event) {
    event.preventDefault(); // 기본 제출 동작 중단

    const customerName = document.getElementById('CustomerName').value.trim();
    const phoneNumber = document.getElementById('PhoneNumber').value.trim();
    const address = document.getElementById('Address').value.trim();
    const paymentStatus = document.getElementById('PaymentStatus').value;
    const paymentMethod = document.getElementById('PaymentMethod').value;
    const Cost = document.getElementById('Cost').value;

    if (!customerName) {
        alert("고객명은 필수 입력 사항입니다.");
        document.getElementById('CustomerName').focus();
        return false;
    }

    if (!phoneNumber) {
        alert("전화번호는 필수 입력 사항입니다.");
        document.getElementById('PhoneNumber').focus();
        return false;
    }

    if (!address) {
        alert("주소는 필수 입력 사항입니다.");
        document.getElementById('Address').focus();
        return false;
    }

    if (!Cost) {
        alert("금액은 필수 입력 사항입니다.");
        document.getElementById('Cost').focus();
        return false;
    }

    if (paymentStatus === "입금완료" && !paymentMethod) {
        alert("입금여부가 '입금완료'일 경우 '입금방법'을 선택해야 합니다.");
        document.getElementById('PaymentMethod').focus();
        return false;
    }

    document.getElementById('dataForm').submit();
}

// "고객명과 동일" 체크박스를 통해 주소 필드를 동기화하거나 해제하는 함수
function toggleSyncAddress() {
    const checkbox = document.getElementById('sameAsCustomerName');
    const customerName = document.getElementById('CustomerName').value.trim();
    const addressField = document.getElementById('Address');

    if (checkbox.checked) {
        addressField.value = customerName;
        addressField.readOnly = true;
    } else {
        addressField.value = '';
        addressField.readOnly = false;
    }
}

// 고객명 입력 시 체크박스 상태에 따라 주소를 동기화하는 함수
function syncAddress() {
    const checkbox = document.getElementById('sameAsCustomerName');
    const customerName = document.getElementById('CustomerName').value.trim();
    const addressField = document.getElementById('Address');

    if (checkbox.checked) {
        addressField.value = customerName;
    }
}

// 이미지 소스를 받아 사진 모달을 표시하는 함수
function showPhotoModal(imageSrc) {
    var modal = document.getElementById("photoModal");
    var modalImage = document.getElementById("photoModalImg");

    modalImage.src = imageSrc;
    modal.style.display = "block";
}

// 사진 모달을 숨기는 함수
function closePhotoModal() {
    var modal = document.getElementById("photoModal");
    modal.style.display = "none";
}

// 페이지 로드 후 삭제 버튼에 이벤트 리스너를 추가하는 함수
document.addEventListener("DOMContentLoaded", function () {
    const deleteButtons = document.querySelectorAll(".deleteMemo");
    deleteButtons.forEach(function (button) {
        button.addEventListener("click", function () {
            const memoID = this.getAttribute("data-memo-id");
            if (confirm("메모를 삭제하시겠습니까?")) {
                if (memoID) {
                    sendDeleteRequest(memoID);
                } else {
                    alert("삭제 데이터가 유효하지 않습니다.");
                }
            }
        });
    });
});

// 메모 삭제 요청을 서버로 보내는 함수
function sendDeleteRequest(memoID) {
    const xhr = new XMLHttpRequest();
    xhr.open("GET", "cb.asp?action=deleteMemo&memoID=" + memoID, true);
    xhr.onreadystatechange = function () {
        if (xhr.readyState === 4 && xhr.status === 200) {
            if (xhr.responseText.trim() === "success") {
                location.reload();
            } else if (xhr.responseText.trim() === "invalid-id") {
                alert("삭제할 메모의 ID가 유효하지 않습니다.");
            } else {
                alert("메모 삭제에 실패했습니다.");
            }
        }
    };
    xhr.send();
}

// 메모 모달을 열고 주문 ID를 설정하는 함수
function openMemoModal(orderId) {
    const modal = document.getElementById("memoModal");
    const orderInput = document.getElementById("memoOrderID");
    
    orderInput.value = orderId;
    modal.style.display = "block";
}

// 메모 모달을 닫는 함수
function closeMemoModal() {
    const modal = document.getElementById("memoModal");
    modal.style.display = "none";
}

// 메모 폼 제출 전 유효성을 검사하는 함수
function validateMemoForm() {
    const memoText = document.getElementById("memoText").value;

    if (!memoText.trim()) {
        alert("메모 내용을 입력하세요.");
        return false;
    }
    return true;
}

// 배경 클릭 시 메모 모달을 닫는 이벤트 핸들러
window.onclick = function(event) {
    const modal = document.getElementById("memoModal");
    if (event.target === modal) {
        closeMemoModal();
    }
};

// 버튼 클릭 시 메모와 상태를 설정하는 함수
function setMemoFromButton(event, status) {
    const memoTextArea = document.getElementById('memoText');
    const progressStatusField = document.getElementById('ProgressStatus1');
    const buttonText = event.target.innerText;

    if (memoTextArea) {
        if (memoTextArea.value.trim() !== "") {
            memoTextArea.value += '\n' + buttonText;
        } else {
            memoTextArea.value += buttonText + '\n';
        }
        memoTextArea.focus();
    }

    if (progressStatusField) {
        progressStatusField.value = status;
    }
}

// 날짜/시간 선택기를 토글하는 함수
function toggleDateTimePicker() {
    const dateTimePicker = document.getElementById('dateTimePicker');
    dateTimePicker.style.display = dateTimePicker.style.display === 'none' ? 'block' : 'none';
}

// 선택된 날짜와 시간을 메모에 추가하는 함수
function setConstructionDateTime() {
    const meetingDate = document.getElementById("meetingDate").value;
    const meetingTime = document.getElementById("meetingTime").value;
    const memoTextADD = document.getElementById('memoText').value;

    if (!meetingDate || !meetingTime) {
        alert("날짜와 시간을 모두 선택해주세요.");
        return;
    }

    const constructionDateTime = meetingDate + "T" + meetingTime;
    const date = new Date(constructionDateTime);
    const date1  = meetingDate +" "+ meetingTime;
    if (isNaN(date.getTime())) {
        alert("유효하지 않은 날짜 또는 시간 형식입니다.");
        return;
    }
    const formattedDateTime = formatDateTime(date);
    document.getElementById('memoText').value = memoTextADD + " : " + formattedDateTime;
    document.getElementById('meetingDateTime').value = date1;
}

// 날짜와 시간을 포맷팅하는 함수
function formatDateTime(date) {
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const day = String(date.getDate()).padStart(2, '0');
    const dayOfWeek = ["일", "월", "화", "수", "목", "금", "토"][date.getDay()];
    const hours = date.getHours();
    const minutes = String(date.getMinutes()).padStart(2, '0');

    const amPm = hours < 12 ? "오전" : "오후";
    const formattedHours = hours % 12 === 0 ? 12 : hours % 12;

    return `${month}/${day}(${dayOfWeek}) ${amPm} ${formattedHours}시 ${minutes}분`;
}

// 버튼 클릭 시 메모를 설정하고 특정 조건에서 날짜 선택기를 여는 함수
function setMemoFromButton(event, memo) {
    const memoText = document.getElementById('memoText');
    memoText.value = memo;
  
    if (event.target.id === 'requestConstructionBtn') {
        toggleDateTimePicker();
    } else {
        document.getElementById('ProgressStatus1').value = memo;
    }
}

// 계약일 변경 시 시공일을 자동으로 설정하는 함수
function setConstructionDate() {
    const contractDateInput = document.getElementById('ContractDate');
    const constructionDateInput = document.getElementById('ConstructionDate');

    if (contractDateInput.value) {
        const contractDate = new Date(contractDateInput.value);
        contractDate.setDate(contractDate.getDate() + 7);
        const year = contractDate.getFullYear();
        const month = String(contractDate.getMonth() + 1).padStart(2, '0');
        const day = String(contractDate.getDate()).padStart(2, '0');
        constructionDateInput.value = `${year}-${month}-${day}`;
    }
}

// 페이지 떠나기 전 스크롤 위치를 저장하는 이벤트 핸들러
window.addEventListener('beforeunload', function () {
    sessionStorage.setItem('scrollPosition', window.scrollY);
});

// 페이지 로드 시 저장된 스크롤 위치로 이동하는 이벤트 핸들러
window.addEventListener('load', function () {
    const scrollPosition = sessionStorage.getItem('scrollPosition');
    if (scrollPosition) {  
        window.scrollTo(0, scrollPosition);
    }
});

// 진행 상태에 따라 검색 조건을 설정하고 폼을 제출하는 함수
function setProgressStatus(value) {
    document.getElementById("searchProgressStatus").value = value;
    document.getElementById("searchForm").submit();
}