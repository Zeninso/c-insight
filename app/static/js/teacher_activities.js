// teacher_activities.js

// Modal functions
function showCreateActivityModal() {
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
            <p><strong>Class:</strong> ${activity.class_name || 'N/A'}</p>
            <p><strong>Description:</strong> ${activity.description || 'N/A'}</p>
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

// Update total weight (edit form)
function updateEditTotalWeight() {
    const total = Array.from(document.querySelectorAll('#edit-rubrics-container .weight-input'))
        .reduce((sum, input) => sum + (parseInt(input.value) || 0), 0);
    
    document.getElementById('edit-total-weight').textContent = total + '%';
    
    const errorElement = document.getElementById('edit-weight-error');
    const submitBtn = document.getElementById('edit-submit-btn');
    
    if (total !== 100) {
        errorElement.textContent = 'Total weight must equal 100%';
        submitBtn.disabled = true;
    } else {
        errorElement.textContent = '';
        submitBtn.disabled = false;
    }
}

// Logout confirmation
function confirmLogout() {
    Swal.fire({
        title: 'Logout?',
        text: "Are you sure you want to logout?",
        icon: 'question',
        showCancelButton: true,
        confirmButtonColor: '#3085d6',
        cancelButtonColor: '#d33',
        confirmButtonText: 'Yes, logout!'
    }).then((result) => {
        if (result.isConfirmed) {
            window.location.href = logoutUrl;
        }
    });
}

// Delete activity
function deleteActivity(activityId) {
    Swal.fire({
        title: 'Are you sure?',
        text: 'This will permanently delete the activity.',
        icon: 'warning',
        showCancelButton: true,
        confirmButtonText: 'Yes, delete it!'
    }).then((result) => {
        if (result.isConfirmed) {
            fetch(`/teacher/activity/${activityId}`, { method: 'DELETE' })
                .then(res => res.json())
                .then(data => {
                    if (data.success) {
                        Swal.fire('Deleted!', 'Activity has been deleted.', 'success')
                            .then(() => location.reload());
                    } else {
                        Swal.fire('Error!', data.error, 'error');
                    }
                });
        }
    });
}

// Update total weight (create form)
function updateTotalWeight() {
    const total = Array.from(document.querySelectorAll('.weight-input'))
        .reduce((sum, input) => sum + (parseInt(input.value) || 0), 0);
    
    document.getElementById('total-weight').textContent = total + '%';
    
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
    
    const totalWeight = Array.from(document.querySelectorAll('.weight-input'))
        .reduce((sum, input) => sum + (parseInt(input.value) || 0), 0);
    
    if (totalWeight !== 100) {
        Swal.fire('Error', 'Total weights must equal 100%', 'error');
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
            window.location.reload();
        }
    })
    .catch(error => {
        Swal.fire('Error', 'Failed to create activity', 'error');
    });
});

// Form submission (edit activity)
document.getElementById('editActivityForm').addEventListener('submit', function(e) {
    e.preventDefault();
    
    const totalWeight = Array.from(document.querySelectorAll('#edit-rubrics-container .weight-input'))
        .reduce((sum, input) => sum + (parseInt(input.value) || 0), 0);
    
    if (totalWeight !== 100) {
        Swal.fire('Error', 'Total weights must equal 100%', 'error');
        return;
    }
    
    const formData = new FormData(this);
    const activityId = document.getElementById('edit_activity_id').value;
    
    fetch(`/teacher/activity/${activityId}`, {
        method: 'PUT',
        body: formData,
        headers: {
            'Accept': 'application/json'
        }
    })
    .then(response => response.json())
    .then(data => {
        if (data.error) {
            Swal.fire('Error', data.error, 'error');
        } else {
            Swal.fire('Success', 'Activity updated successfully', 'success')
                .then(() => {
                    hideEditActivityModal();
                    location.reload();
                });
        }
    })
    .catch(error => {
        Swal.fire('Error', 'Failed to update activity', 'error');
    });
});
