// Teacher Class View JavaScript
document.addEventListener('DOMContentLoaded', function() {
    // Tab switching functionality
    const tabs = document.querySelectorAll('.nav-tab');
    const tabContents = {
        'stream': document.querySelector('.class-info-card'),
        'students': document.querySelector('#students-section'),   // Students section
        'classwork': document.querySelector('#classwork-section')  // Classwork section (Activities)
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

    // Initialize with stream tab active and hide other sections
    Object.values(tabContents).forEach((content, index) => {
        if (index > 0 && content) { // Hide all except first tab (stream)
            content.style.display = 'none';
        }
    });
    switchTab('stream');
});

// Function to open create activity modal with pre-selected class
function openCreateActivityModalForClass(classId) {
    // Show the create activity modal
    const modal = document.getElementById('createActivityModal');
    if (modal) {
        modal.style.display = 'block';

        // Set the class_id in the create activity form
        let classIdInput = document.getElementById('createActivityForm').querySelector('input[name="class_id"]');
        if (!classIdInput) {
            // If the hidden input doesn't exist, create it
            classIdInput = document.createElement('input');
            classIdInput.type = 'hidden';
            classIdInput.name = 'class_id';
            document.getElementById('createActivityForm').appendChild(classIdInput);
        }
        classIdInput.value = classId;
    } else {
        console.error('Create activity modal not found');
    }
}
