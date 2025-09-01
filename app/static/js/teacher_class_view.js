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

    // Initialize with stream tab active and hide other sections
    Object.values(tabContents).forEach((content, index) => {
        if (index > 0 && content) { // Hide all except first tab (stream)
            content.style.display = 'none';
        }
    });
    switchTab('stream');
});

