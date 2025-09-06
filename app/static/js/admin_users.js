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
                    .then(res => res.json())
                    .then(data => {
                        if (data.success) {
                            Swal.fire('Deleted!', 'User has been deleted.', 'success')
                                .then(() => location.reload());
                        } else {
                            Swal.fire('Error!', data.error, 'error');
                        }
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
                Swal.fire('Updated!', 'User has been updated.', 'success')
                    .then(() => location.reload());
            } else {
                Swal.fire('Error!', data.error, 'error');
            }
        });
    });

    function confirmLogout() {
        Swal.fire({
            title: 'Logout?',
            text: "Are you sure you want to logout?",
            icon: 'question',
            showCancelButton: true,
            confirmButtonColor: ' #6f42c1',
            cancelButtonColor: '#d33',
            confirmButtonText: 'Yes, logout!'
        }).then((result) => {
            if (result.isConfirmed) {
                window.location.href = "{{ url_for('auth.logout') }}";
            }
        });
    }

  