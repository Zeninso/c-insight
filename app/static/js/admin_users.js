    function confirmDelete(userId) {
        Swal.fire({
            title: 'Are you sure?',
            text: 'This will permanently delete the user.',
            icon: 'warning',
            showCancelButton: true,
            confirmButtonText: 'Yes, delete it!'
        }).then((result) => {
            if (result.isConfirmed) {
                fetch(`/admin/user/${userId}/delete`, { method: 'POST' })
                    .then(res => {
                        if (!res.ok) {
                            throw new Error(`HTTP ${res.status}: ${res.statusText}`);
                        }
                        return res.json();
                    })
                    .then(data => {
                        console.log('Delete response:', data);
                        if (data.success) {
                            Swal.fire({
                                title: 'Deleted!',
                                text: 'User has been deleted.',
                                icon: 'success',
                                showConfirmButton: false,
                                timer: 1500
                            }).then(() => location.reload());
                        } else {
                            Swal.fire('Error!', data.error, 'error');
                        }
                    })
                    .catch(error => {
                        console.error('Delete error:', error);
                        Swal.fire('Error!', 'Failed to delete user: ' + error.message, 'error');
                    });
            }
        });
    }

    function editUser(userId) {
        // Find the user row by id
        const row = document.getElementById('user-' + userId);
        if (!row) return;

        // Populate modal fields with user data attributes
        document.getElementById('modalUserId').value = userId;
        document.getElementById('modalUsername').value = row.getAttribute('data-username');
        document.getElementById('modalFirstName').value = row.getAttribute('data-firstname');
        document.getElementById('modalLastName').value = row.getAttribute('data-lastname');
        document.getElementById('modalEmail').value = row.getAttribute('data-email');
        document.getElementById('modalRole').value = row.getAttribute('data-role');

        // Set form action URL dynamically
        document.getElementById('editUserForm').action = '/admin/user/' + userId + '/edit';

        // Show the modal with fade-in
        const modal = document.getElementById('editUserModal');
        modal.style.display = 'block';
        setTimeout(() => {
            modal.style.opacity = '1';
        }, 10);
    }

    function closeEditModal() {
        const modal = document.getElementById('editUserModal');
        modal.style.opacity = '0';
        setTimeout(() => {
            modal.style.display = 'none';
        }, 300);
    }

    // Close modal when clicking outside the modal content
    window.onclick = function(event) {
        const modal = document.getElementById('editUserModal');
        if (event.target == modal) {
            closeEditModal();
        }
    }

    // Handle edit form submission
    document.getElementById('editUserForm').addEventListener('submit', function(e) {
        e.preventDefault();
        const formData = new FormData(this);
        fetch(this.action, {
            method: 'POST',
            body: formData
        })
        .then(res => res.json())
        .then(data => {
            if (data.success) {
                Swal.fire({
                    title: 'Updated!',
                    text: 'User has been updated.',
                    icon: 'success',
                    showConfirmButton: false,
                    timer: 1500
                }).then(() => location.reload());
            } else {
                Swal.fire('Error!', data.error, 'error');
            }
        });
    });

    // Search and Filter functionality
    const searchInput = document.getElementById('searchInput');
    const roleFilter = document.getElementById('roleFilter');
    const tableRows = document.querySelectorAll('tbody tr');

    function filterTable() {
        const searchTerm = searchInput.value.toLowerCase();
        const selectedRole = roleFilter.value;

        tableRows.forEach(row => {
            const username = row.getAttribute('data-username').toLowerCase();
            const firstname = row.getAttribute('data-firstname').toLowerCase();
            const lastname = row.getAttribute('data-lastname').toLowerCase();
            const email = row.getAttribute('data-email').toLowerCase();
            const role = row.getAttribute('data-role');

            const matchesSearch = username.includes(searchTerm) || firstname.includes(searchTerm) || lastname.includes(searchTerm) || email.includes(searchTerm);
            const matchesRole = !selectedRole || role === selectedRole;

            row.style.display = matchesSearch && matchesRole ? '' : 'none';
        });
    }

    searchInput.addEventListener('input', filterTable);
    roleFilter.addEventListener('change', filterTable);

    // Bulk Actions
    const selectAllCheckbox = document.getElementById('selectAll');
    const userCheckboxes = document.querySelectorAll('.userCheckbox');
    const bulkActions = document.getElementById('bulkActions');
    const selectedCount = document.getElementById('selectedCount');

    function updateBulkActions() {
        const checkedBoxes = document.querySelectorAll('.userCheckbox:checked');
        const count = checkedBoxes.length;
        selectedCount.textContent = `${count} selected`;
        bulkActions.style.display = count > 0 ? 'block' : 'none';
    }

    selectAllCheckbox.addEventListener('change', function() {
        userCheckboxes.forEach(cb => cb.checked = this.checked);
        updateBulkActions();
    });

    userCheckboxes.forEach(cb => {
        cb.addEventListener('change', function() {
            const allChecked = Array.from(userCheckboxes).every(cb => cb.checked);
            const someChecked = Array.from(userCheckboxes).some(cb => cb.checked);
            selectAllCheckbox.checked = allChecked;
            selectAllCheckbox.indeterminate = someChecked && !allChecked;
            updateBulkActions();
        });
    });

    // Bulk Delete
    window.confirmBulkDelete = function() {
        const selectedIds = Array.from(document.querySelectorAll('.userCheckbox:checked')).map(cb => cb.value);
        if (selectedIds.length === 0) return;

        Swal.fire({
            title: 'Are you sure?',
            text: `This will permanently delete ${selectedIds.length} user(s).`,
            icon: 'warning',
            showCancelButton: true,
            confirmButtonText: 'Yes, delete them!'
        }).then((result) => {
            if (result.isConfirmed) {
                // Delete one by one or send bulk request
                let deleted = 0;
                selectedIds.forEach(id => {
                    fetch(`/admin/user/${id}/delete`, { method: 'POST' })
                        .then(res => res.json())
                        .then(data => {
                            if (data.success) {
                                deleted++;
                                if (deleted === selectedIds.length) {
                                    Swal.fire({
                                        title: 'Deleted!',
                                        text: 'Users have been deleted.',
                                        icon: 'success',
                                        showConfirmButton: false,
                                        timer: 1500
                                    }).then(() => location.reload());
                                }
                            } else {
                                Swal.fire('Error!', data.error, 'error');
                            }
                        });
                });
            }
        });
    };

    // Bulk Change Role
    window.bulkChangeRole = function() {
        const selectedIds = Array.from(document.querySelectorAll('.userCheckbox:checked')).map(cb => cb.value);
        const newRole = document.getElementById('bulkRoleSelect').value;
        if (selectedIds.length === 0 || !newRole) return;

        // For simplicity, update one by one
        let updated = 0;
        selectedIds.forEach(id => {
            const formData = new FormData();
            formData.append('role', newRole);

            fetch(`/admin/user/${id}/edit`, {
                method: 'POST',
                body: formData
            })
            .then(res => res.json())
            .then(data => {
                if (data.success) {
                    updated++;
                    if (updated === selectedIds.length) {
                        Swal.fire({
                            title: 'Updated!',
                            text: 'Roles have been updated.',
                            icon: 'success',
                            showConfirmButton: false,
                            timer: 1500
                        }).then(() => location.reload());
                    }
                } else {
                    Swal.fire('Error!', data.error, 'error');
                }
            });
        });
    };

  