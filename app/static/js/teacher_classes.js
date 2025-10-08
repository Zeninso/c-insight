function confirmLogout() {
        Swal.fire({
            title: 'Logout?',
            text: "Are you sure you want to logout?",
            icon: 'question',
            showCancelButton: true,
            confirmButtonColor: ' #6f42c1',
            cancelButtonColor: '#6c757d',
            confirmButtonText: 'Yes, logout!'
        }).then((result) => {
            if (result.isConfirmed) {
                window.location.href = urls.logout;
            }
        });
    }
    
    // Handle class creation form
    document.getElementById('createClassForm').addEventListener('submit', async function(e) {
        e.preventDefault();

        const formData = new FormData(this);

        try {
            const response = await fetch(urls.createClass, {
                method: 'POST',
                body: formData
            });
            
            const result = await response.json();
            
            if (response.ok) {
                Swal.fire({
                    title: 'Success!',
                    html: `Class created successfully!<br><br>
                            Your class code is: <strong>${result.class_code}</strong><br>
                            This code will expire on ${result.expires}`,
                    icon: 'success',
                    showConfirmButton: false,
                    timer: 1500
                }).then(() => {
                    window.location.reload();
                });
            } else {
                Swal.fire('Error', result.error, 'error');
            }
        } catch (error) {
            Swal.fire('Error', 'An error occurred while creating the class', 'error');
        }
    });
    
    // Copy code functionality
    document.querySelectorAll('.btn-copy').forEach(button => {
        button.addEventListener('click', function() {
            const code = this.getAttribute('data-code');
            navigator.clipboard.writeText(code).then(() => {
                const originalHtml = this.innerHTML;
                this.innerHTML = '<i class="fas fa-check"></i>';
                
                setTimeout(() => {
                    this.innerHTML = originalHtml;
                }, 2000);
            });
        });
    });

    // Modal handling
    const modal = document.getElementById('createClassModal');
    const btn = document.getElementById('createClassBtn');
    const span = document.getElementsByClassName('close')[0];

    btn.onclick = function() {
        modal.style.display = "block";
    }

    span.onclick = function() {
        modal.style.display = "none";
    }

    window.onclick = function(event) {
        if (event.target == modal) {
            modal.style.display = "none";
        }
    }

    // Handle code regeneration
    document.querySelectorAll('.regenerate-form').forEach(form => {
        form.addEventListener('submit', async function(e) {
            e.preventDefault();

            Swal.fire({
                title: 'Regenerate Code?',
                text: "This will invalidate the current code and generate a new one.",
                icon: 'warning',
                showCancelButton: true,
                confirmButtonColor: ' #6f42c1',
                cancelButtonColor: '#6c757d',
                confirmButtonText: 'Yes, regenerate!'
            }).then(async (result) => {
                if (result.isConfirmed) {
                    try {
                        const response = await fetch(this.action, {
                            method: 'POST'
                        });

                        const result = await response.json();

                        if (response.ok) {
                            Swal.fire({
                                title: 'Success!',
                                html: `New class code generated!<br><br>
                                        Your new class code is: <strong>${result.class_code}</strong><br>
                                        This code will expire on ${result.expires}`,
                                icon: 'success',
                                showConfirmButton: false,
                                timer: 1500
                            }).then(() => {
                                window.location.reload();
                            });
                        } else {
                            Swal.fire('Error', result.error, 'error');
                        }
                    } catch (error) {
                        Swal.fire('Error', 'An error occurred while regenerating the code', 'error');
                    }
                }
            });
        });
    });

    // Handle class removal
    document.querySelectorAll('.btn-remove-class').forEach(button => {
        button.addEventListener('click', async function() {
            const classId = this.getAttribute('data-class-id');

            Swal.fire({
                title: 'Delete Class?',
                text: "Are you sure you want to delete this class? This will also delete all associated activities and submissions.",
                icon: 'warning',
                showCancelButton: true,
                confirmButtonColor: '#d33',
                cancelButtonColor: '#6c757d',
                confirmButtonText: 'Yes, delete it!'
            }).then(async (result) => {
                if (result.isConfirmed) {
                    try {
                        const response = await fetch(urls.deleteClass.replace('0', classId), {
                            method: 'POST'
                        });

                        const result = await response.json();

                        if (response.ok) {
                            Swal.fire({
                                title: 'Deleted!',
                                text: 'The class and all associated activities have been deleted.',
                                icon: 'success',
                                showConfirmButton: false,
                                timer: 1500
                            }).then(() => {
                                window.location.reload();
                            });
                        } else {
                            Swal.fire('Error', result.error, 'error');
                        }
                    } catch (error) {
                        Swal.fire('Error', 'An error occurred while deleting the class', 'error');
                    }
                }
            });
        });
    });