// teacher_activities.js

// Modal functions
function showCreateActivityModal() {
    hideEditActivityModal(); // Close edit modal if open
    document.getElementById('createActivityForm').reset();
    updateTotalWeight();
    // Clear test cases container
    document.getElementById('test-cases-container').innerHTML = '';
    document.getElementById('createActivityModal').style.display = 'block';
}

function hideCreateActivityModal() {
    document.getElementById('createActivityModal').style.display = 'none';
}

function showViewActivityModal(activityId) {
    fetch(`/teacher/activity/${activityId}`)
        .then(response => response.json())
        .then(data => {
            if (data.error) {
                Swal.fire('Error', data.error, 'error');
            } else {
                document.getElementById('viewActivityContent').innerHTML = formatActivityView(data);
                document.getElementById('viewActivityModal').style.display = 'block';
            }
        })
        .catch(error => {
            Swal.fire('Error', 'Failed to load activity details', 'error');
        });
}

function hideViewActivityModal() {
    document.getElementById('viewActivityModal').style.display = 'none';
}

function showEditActivityModal(activityId) {
    fetch(`/teacher/activity/${activityId}`)
        .then(response => response.json())
        .then(data => {
            if (data.error) {
                Swal.fire('Error', data.error, 'error');
            } else {
                populateEditForm(data);
                document.getElementById('editActivityModal').style.display = 'block';
            }
        })
        .catch(error => {
            Swal.fire('Error', 'Failed to load activity for editing', 'error');
        });
}

function hideEditActivityModal() {
    document.getElementById('editActivityModal').style.display = 'none';
}

// Format activity data for viewing
function formatActivityView(activity) {
    return `
        <div class="activity-section">
            <h3>${activity.title}</h3>
            <p><strong>Class:</strong> ${ activity.class_name || 'N/A'}</p>
        </div>

        <div class="activity-section">
            <h4>Description</h4>
            <p>${activity.description || 'N/A'}</p>
        </div>

        <div class="activity-section">
            <h4>Instructions</h4>
            <pre>${activity.instructions}</pre>
        </div>
        
        ${activity.starter_code ? `
        <div class="activity-section">
            <h4>Starter Code</h4>
            <pre>${activity.starter_code}</pre>
        </div>
        ` : ''}
        
        <div class="activity-section">
            <h4>Due Date</h4>
            <p>${new Date(activity.due_date).toLocaleString()}</p>
        </div>

        ${activity.test_cases && activity.test_cases.length > 0 ? `
        <div class="test-cases-section">
            <h3>Test Cases</h3>
            <div class="test-cases-list">
                ${activity.test_cases.map((testCase, index) => `
                    <div class="test-case">
                        <h4>Test Case ${index + 1}</h4>
                        <p><strong>Input:</strong></p>
                        <pre>${testCase.input}</pre>
                        <p><strong>Expected Output:</strong></p>
                        <pre>${testCase.output}</pre>
                    </div>
                `).join('')}
            </div>
        </div>
        ` : ''}

        <div class="activity-section">
            <h4>Rubrics</h4>
            <table class="rubrics-table">
                <thead>
                    <tr>
                        <th>Criterion</th>
                        <th>Weight</th>
                    </tr>
                </thead>
                <tbody>
                    <tr>
                        <td>Correctness</td>
                        <td>${activity.correctness_weight}%</td>
                    </tr>
                    <tr>
                        <td>Syntax</td>
                        <td>${activity.syntax_weight}%</td>
                    </tr>
                    <tr>
                        <td>Logic</td>
                        <td>${activity.logic_weight}%</td>
                    </tr>
                    <tr>
                        <td>Similarity</td>
                        <td>${activity.similarity_weight}%</td>
                    </tr>
                </tbody>
                <tfoot>
                    <tr>
                        <td><strong>Total</strong></td>
                        <td><strong>${parseInt(activity.correctness_weight) + parseInt(activity.syntax_weight) + parseInt(activity.logic_weight) + parseInt(activity.similarity_weight)}%</strong></td>
                    </tr>
                </tfoot>
            </table>
        </div>
        
        <div class="activity-stats">
            <div class="stat-card">
                <h4>Submissions</h4>
                <p>${activity.submission_count || 0}</p>
            </div>
        </div>
        
        <div class="activity-actions">
            <button class="btn btn-gradient" onclick="showEditActivityModal('${activity.id}')">Edit Activity</button>
            <button class="btn btn-danger" onclick="deleteActivity('${activity.id}')">Delete Activity</button>
        </div>
    `;
}

// Populate edit form
function populateEditForm(activity) {
    document.getElementById('edit_activity_id').value = activity.id;
    document.getElementById('edit_class_id').value = activity.class_id;
    document.getElementById('edit_title').value = activity.title;
    document.getElementById('edit_description').value = activity.description || '';
    document.getElementById('edit_instructions').value = activity.instructions;
    document.getElementById('edit_starter_code').value = activity.starter_code || '';

    const dueDate = new Date(activity.due_date);
    const formattedDate = dueDate.toISOString().slice(0, 16);
    document.getElementById('edit_due_date').value = formattedDate;

    // Clear and populate test cases
    const editTestCasesContainer = document.getElementById('edit-test-cases-container');
    editTestCasesContainer.innerHTML = '';

    if (activity.test_cases && Array.isArray(activity.test_cases)) {
        activity.test_cases.forEach(testCase => {
            addEditTestCase(testCase);
        });
        updateTestCaseNumbers(); 
    }

    const rubricsContainer = document.getElementById('edit-rubrics-container');
    rubricsContainer.innerHTML = `
        <div class="rubric-item">
            <input type="text" name="rubric_name[]" value="Correctness" required readonly>
            <input type="number" name="rubric_weight[]" min="0" max="100" value="${activity.correctness_weight}" class="weight-input" required>
        </div>
        <div class="rubric-item">
            <input type="text" name="rubric_name[]" value="Syntax" required readonly>
            <input type="number" name="rubric_weight[]" min="0" max="100" value="${activity.syntax_weight}" class="weight-input" required>
        </div>
        <div class="rubric-item">
            <input type="text" name="rubric_name[]" value="Logic" required readonly>
            <input type="number" name="rubric_weight[]" min="0" max="100" value="${activity.logic_weight}" class="weight-input" required>
        </div>
        <div class="rubric-item">
            <input type="text" name="rubric_name[]" value="Similarity" required readonly>
            <input type="number" name="rubric_weight[]" min="0" max="100" value="${activity.similarity_weight}" class="weight-input" required>
        </div>
    `;
    updateEditTotalWeight();
}

// Update total weight (edit form) - Enhanced UI/UX
function updateEditTotalWeight() {
    const total = Array.from(document.querySelectorAll('#edit-rubrics-container .weight-input'))
        .reduce((sum, input) => sum + (parseInt(input.value) || 0), 0);
    
    const totalWeightSpan = document.getElementById('edit-total-weight');
    totalWeightSpan.textContent = total + '%';
    
    const errorElement = document.getElementById('edit-weight-error');
    const submitBtn = document.getElementById('edit-submit-btn');
    
    if (total !== 100) {
        errorElement.textContent = 'Total weight must equal 100%';
        totalWeightSpan.style.color = 'red';
        totalWeightSpan.style.fontWeight = 'bold';
        submitBtn.disabled = true;
    } else {
        errorElement.textContent = '';
        totalWeightSpan.style.color = 'green';
        totalWeightSpan.style.fontWeight = 'bold';
        submitBtn.disabled = false;
    }
}


// Delete activity
function deleteActivity(activityId) {
    Swal.fire({
        title: 'Are you sure?',
        text: 'This will permanently delete the activity.',
        icon: 'warning',
        showCancelButton: true,
        confirmButtonText: 'Yes, delete it!',
        confirmButtonColor: '#d33'
    }).then((result) => {
        if (result.isConfirmed) {
            fetch(`/teacher/activity/${activityId}`, { method: 'DELETE' })
                .then(res => res.json())
                .then(data => {
                    if (data.success) {
                        Swal.fire({
                            title: 'Deleted!',
                            text: 'Activity has been deleted.',
                            icon: 'success',
                            showConfirmButton: false,
                            timer: 1500
                        }).then(() => location.reload());
                    } else {
                        Swal.fire('Error!', data.error, 'error');
                    }
                });
        }
    });
}

// Update total weight (create form)
function updateTotalWeight() {
    const total = Array.from(document.querySelectorAll('#createActivityModal .weight-input'))
        .reduce((sum, input) => sum + (parseInt(input.value) || 0), 0);

    const totalWeightSpan = document.getElementById('total-weight');
    totalWeightSpan.textContent = total + '%';

    if (total !== 100) {
        totalWeightSpan.style.color = 'red';
    } else {
        totalWeightSpan.style.color = 'black';
    }

    const errorElement = document.getElementById('weight-error');
    const submitBtn = document.getElementById('submit-btn');

    if (total !== 100) {
        errorElement.textContent = 'Total weight must equal 100%';
        submitBtn.disabled = true;
    } else {
        errorElement.textContent = '';
        submitBtn.disabled = false;
    }
}

// Attach listener dynamically for rubric inputs
document.addEventListener('input', function(e) {
    if (e.target.classList.contains('weight-input')) {
        if (e.target.closest('#edit-rubrics-container')) {
            updateEditTotalWeight();
        } else {
            updateTotalWeight();
        }
    }
});

// Initialize total weight
updateTotalWeight();

// Form submission (create activity)
document.getElementById('createActivityForm').addEventListener('submit', function(e) {
    e.preventDefault();

    const totalWeight = Array.from(document.querySelectorAll('#createActivityModal .weight-input'))
        .reduce((sum, input) => sum + (parseInt(input.value) || 0), 0);

    if (totalWeight !== 100) {
        Swal.fire('Error', 'Total weights must equal 100%', 'error');
        return;
    }

    if (!validateTestCases()) {
        return;
    }

    const formData = new FormData(this);

    fetch(this.action, {
        method: 'POST',
        body: formData,
        headers: {
            'Accept': 'application/json'
        }
    })
    .then(response => {
        if (response.redirected) {
            window.location.href = response.url;
        } else {
            return response.json();
        }
    })
    .then(data => {
        if (data && data.error) {
            Swal.fire('Error', data.error, 'error');
        } else {
            Swal.fire({
                title: 'Success',
                text: 'Activity created successfully',
                icon: 'success',
                showConfirmButton: false,
                timer: 1500
            }).then(() => {
                hideCreateActivityModal();
                location.reload();
            });
        }
    })
    .catch(error => {
        Swal.fire('Error', 'Failed to create activity', 'error');
    });
});


document.getElementById('editActivityForm').addEventListener('submit', function(e) {
    e.preventDefault();

    const classIdInput = document.getElementById('edit_class_id');
    

    if (classIdInput.value === "") {
        Swal.fire('Error', 'You must select a class for the activity.', 'error');
        return; 
    }

    const totalWeight = Array.from(document.querySelectorAll('#edit-rubrics-container .weight-input'))
        .reduce((sum, input) => sum + (parseInt(input.value) || 0), 0);

    if (totalWeight !== 100) {
        Swal.fire('Error', 'Total weights must equal 100%', 'error');
        return;
    }

    if (!validateTestCases()) {
        return;
    }

    const formData = new FormData(this);
    const activityId = document.getElementById('edit_activity_id').value;
    const submitBtn = document.getElementById('edit-submit-btn');

    // Set loading state
    submitBtn.textContent = 'Updating...';
    submitBtn.disabled = true;

    fetch(`/teacher/activity/${activityId}`, {
        method: 'PUT',
        body: formData,
        headers: {
            'Accept': 'application/json'
        }
    })
    .then(response => response.json())
    .then(data => {
        // Reset button state
        submitBtn.innerHTML = '<i class="fas fa-save"></i> Update Activity';
        submitBtn.disabled = false;

        if (data.error) {
            Swal.fire('Error', data.error, 'error');
        } else {
            Swal.fire({
                title: 'Success',
                text: 'Activity updated successfully',
                icon: 'success',
                showConfirmButton: false,
                timer: 1500
            }).then(() => {
                hideEditActivityModal();
                location.reload();
            });
        }
    })
    .catch(error => {
        // Reset button state on failure
        submitBtn.innerHTML = '<i class="fas fa-save"></i> Update Activity';
        submitBtn.disabled = false;
        Swal.fire('Error', 'Failed to update activity', 'error');
    });
});


// Test case functions
function addTestCase(existingTestCase = null) {
    const container = document.getElementById('test-cases-container');
    const testCaseDiv = document.createElement('div');
    testCaseDiv.className = 'test-case-item card-test-case';
    
    const index = container.children.length + 1;

    testCaseDiv.innerHTML = `
        <div class="test-case-header">
            <h4>Test Case ${index}</h4>
            <button type="button" class="btn btn-danger btn-sm remove-btn" onclick="removeTestCase(this, 'create')"><i class="fas fa-minus-circle"></i> Remove</button>
        </div>
        <div class="test-case-content">
            <label>Input:</label>
            <textarea name="test_case_input[]" placeholder="Enter input for test case" required>${existingTestCase ? existingTestCase.input : ''}</textarea>
            <label>Expected Output:</label>
            <textarea name="test_case_output[]" placeholder="Enter expected output" required>${existingTestCase ? existingTestCase.output : ''}</textarea>
        </div>
    `;
    container.appendChild(testCaseDiv);
    updateTestCaseNumbers('create');
}

// Test case functions for EDIT modal
function addEditTestCase(existingTestCase = null) {
    const container = document.getElementById('edit-test-cases-container');
    const testCaseDiv = document.createElement('div');
    testCaseDiv.className = 'test-case-item card-test-case';
    
    const index = container.children.length + 1;

    testCaseDiv.innerHTML = `
        <div class="test-case-header">
            <h4>Test Case ${index}</h4>
            <button type="button" class="btn btn-danger btn-sm remove-btn" onclick="removeTestCase(this, 'edit')"><i class="fas fa-minus-circle"></i> Remove</button>
        </div>
        <div class="test-case-content">
            <label>Input:</label>
            <textarea name="test_case_input[]" placeholder="Enter input for test case" required>${existingTestCase ? existingTestCase.input : ''}</textarea>
            <label>Expected Output:</label>
            <textarea name="test_case_output[]" placeholder="Enter expected output" required>${existingTestCase ? existingTestCase.output : ''}</textarea>
        </div>
    `;
    container.appendChild(testCaseDiv);
    updateTestCaseNumbers('edit');
}

function removeTestCase(button, formType) {
    button.parentElement.parentElement.remove(); 
    updateTestCaseNumbers(formType);
}

// New function to re-number test cases after adding or removing
function updateTestCaseNumbers(formType) {
    const containerId = formType === 'edit' ? 'edit-test-cases-container' : 'test-cases-container';
    const container = document.getElementById(containerId);

    Array.from(container.children).forEach((item, index) => {
        const header = item.querySelector('.test-case-header h4');
        if (header) {
            header.textContent = `Test Case ${index + 1}`;
        }
    });
}

// Form validation for test cases
function validateTestCases() {
    const inputs = document.querySelectorAll('textarea[name="test_case_input[]"]');
    const outputs = document.querySelectorAll('textarea[name="test_case_output[]"]');

    if (inputs.length !== outputs.length) {
        Swal.fire('Error', 'Test case inputs and outputs must be paired', 'error');
        return false;
    }

    for (let i = 0; i < inputs.length; i++) {
        if (!inputs[i].value.trim() || !outputs[i].value.trim()) {
            Swal.fire('Error', 'All test case inputs and outputs must be filled', 'error');
            return false;
        }
    }

    return true;
}

// Logout confirmation
function confirmLogout() {
    Swal.fire({
        title: 'Logout?',
        text: "Are you sure you want to logout?",
        icon: 'question',
        showCancelButton: true,
        confirmButtonColor: ' #6f42c1',
        cancelButtonColor:  '#d33',
        confirmButtonText: 'Yes, logout!'
    }).then((result) => {
        if (result.isConfirmed) {
            window.location.href = logoutUrl;
        }
    });
}