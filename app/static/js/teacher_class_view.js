// Teacher Class View JavaScript
document.addEventListener('DOMContentLoaded', function() {
    // Tab switching functionality
    const tabs = document.querySelectorAll('.nav-tab');
    const tabContents = {
        'stream': document.querySelector('.class-info-card'),
        'students': document.querySelector('#students-section'),  
        'classwork': document.querySelector('#classwork-section')  
    };

    // Function to switch tabs
    function switchTab(tabName) {
        // Remove active class from all tabs
        tabs.forEach(tab => tab.classList.remove('active'));
        
        // Add active class to clicked tab
        const activeTab = document.querySelector(`[data-tab="${tabName}"]`);
        if (activeTab) {
            activeTab.classList.add('active');
        }

        // Hide all content sections
        Object.values(tabContents).forEach(content => {
            if (content) {
                content.style.display = 'none';
            }
        });

        // Show the selected content section
        if (tabContents[tabName]) {
            tabContents[tabName].style.display = 'block';
        }
    }

    // Add click event listeners to tabs
    tabs.forEach(tab => {
        tab.addEventListener('click', function(e) {
            e.preventDefault();
            const tabName = this.getAttribute('data-tab');
            switchTab(tabName);
        });
    });

    // Initialize with classwork tab active and hide other sections

    // Check URL parameters for initial tab
    const urlParams = new URLSearchParams(window.location.search);
    const initialTab = urlParams.get('tab');
    if (initialTab && tabContents[initialTab]) {
        switchTab(initialTab);
    } else {
        // Default to stream tab if no tab specified
        switchTab('stream');
    }

    // Delete selected students functionality
    const deleteSelectedBtn = document.getElementById('deleteSelectedBtn');
    const deleteStudentsForm = document.getElementById('deleteStudentsForm');
    const selectAllCheckbox = document.getElementById('selectAll');
    const studentCheckboxes = deleteStudentsForm ? deleteStudentsForm.querySelectorAll('input[name="student_ids"]') : [];

    function updateDeleteButtonState() {
        const anyChecked = Array.from(studentCheckboxes).some(cb => cb.checked);
        deleteSelectedBtn.disabled = !anyChecked;
    }

    if (selectAllCheckbox) {
        selectAllCheckbox.addEventListener('change', function() {
            studentCheckboxes.forEach(cb => cb.checked = selectAllCheckbox.checked);
            updateDeleteButtonState();
        });
    }

    studentCheckboxes.forEach(cb => {
        cb.addEventListener('change', function() {
            if (!this.checked && selectAllCheckbox.checked) {
                selectAllCheckbox.checked = false;
            } else if (Array.from(studentCheckboxes).every(cb => cb.checked)) {
                selectAllCheckbox.checked = true;
            }
            updateDeleteButtonState();
        });
    });

    if (deleteSelectedBtn) {
        deleteSelectedBtn.addEventListener('click', function() {
            Swal.fire({
                title: 'Are you sure?',
                text: 'This will permanently Remove the selected students from the class.',
                icon: 'warning',
                showCancelButton: true,
                confirmButtonText: 'Yes, remove them!'
            }).then((result) => {
                if (result.isConfirmed) {
                    // Send AJAX request
                    const formData = new FormData(deleteStudentsForm);
                    fetch(deleteStudentsForm.action, {
                        method: 'POST',
                        body: formData,
                        headers: {
                            'X-Requested-With': 'XMLHttpRequest'
                        }
                    })
                    .then(response => response.json())
                    .then(data => {
                        if (data.success) {
                            Swal.fire({
                                title: 'Success!',
                                text: data.message,
                                icon: 'success',
                                showConfirmButton: false,
                                timer: 2000
                            }).then(() => {
                                window.location.href = window.location.pathname + '?tab=students';
                            });
                        } else {
                            Swal.fire('Error', data.error || 'An error occurred', 'error');
                        }
                    })
                    .catch(error => {
                        Swal.fire('Error', 'An error occurred while removing students', 'error');
                    });
                }
            });
        });
    }
});

