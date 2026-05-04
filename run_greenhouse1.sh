#!/bin/bash

# Job Extraction System Runner
# Runs job ID maintenance followed by main job extraction script

# Configuration
VENV_PATH="venv"
JOBID_SCRIPT="GreenhouseIDMaintain.py"
GREENHOUSE_FOLDER="greenhouse"  # Path to greenhouse folder
MAIN_SCRIPT="main.py"           # Main extraction script
NUM_PARALLEL_INSTANCES=4        # Number of parallel instances to run

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    echo -e "${BLUE}[$(date '+%Y-%m-%d %H:%M:%S')]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[$(date '+%Y-%m-%d %H:%M:%S')] ✅${NC} $1"
}

print_error() {
    echo -e "${RED}[$(date '+%Y-%m-%d %H:%M:%S')] ❌${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[$(date '+%Y-%m-%d %H:%M:%S')] ⚠️${NC} $1"
}

# Function to check if virtual environment exists
check_venv() {
    if [ ! -d "$VENV_PATH" ]; then
        print_error "Virtual environment not found at $VENV_PATH"
        return 1
    fi
    return 0
}

# Function to check if required scripts exist
check_scripts() {
    if [ ! -f "$JOBID_SCRIPT" ]; then
        print_error "Job ID maintenance script not found: $JOBID_SCRIPT"
        return 1
    fi
    
    # Check for main.py in greenhouse folder or current directory
    if [ -d "$GREENHOUSE_FOLDER" ] && [ -f "$GREENHOUSE_FOLDER/$MAIN_SCRIPT" ]; then
        MAIN_SCRIPT_PATH="$GREENHOUSE_FOLDER/$MAIN_SCRIPT"
        print_status "Found main script at: $MAIN_SCRIPT_PATH"
    elif [ -f "$MAIN_SCRIPT" ]; then
        MAIN_SCRIPT_PATH="$MAIN_SCRIPT"
        print_status "Found main script at: $MAIN_SCRIPT_PATH"
    else
        print_error "Main extraction script not found. Checked:"
        echo "  - $GREENHOUSE_FOLDER/$MAIN_SCRIPT"
        echo "  - $MAIN_SCRIPT"
        return 1
    fi
    
    return 0
}

# Function to activate virtual environment
activate_venv() {
    print_status "Activating virtual environment..."
    source "$VENV_PATH/bin/activate"
    
    if [ $? -ne 0 ]; then
        print_error "Failed to activate virtual environment at $VENV_PATH"
        return 1
    fi
    
    print_success "Virtual environment activated"
    return 0
}

# Function to clean up old screen sessions
cleanup_screens() {
    print_status "Cleaning up old screen sessions..."
    
    # Kill specific sessions for job extraction
    screen -ls | grep -E 'jobid_maintain_session|job_extraction_' | awk '{print $1}' | while read session; do
        if [ ! -z "$session" ]; then
            screen -S "$session" -X quit 2>/dev/null
            print_status "Terminated session: $session"
        fi
    done
    
    print_success "Old screen sessions cleaned up"
}

# Function to run job ID maintenance
run_jobid_maintenance() {
    print_status "Starting job ID maintenance script..."
    
    # Start job ID maintenance in screen session
    screen -dmS jobid_maintain_session bash -c "python '$JOBID_SCRIPT'; exec bash"
    
    if [ $? -ne 0 ]; then
        print_error "Failed to start job ID maintenance script"
        return 1
    fi
    
    # Wait for job ID maintenance to complete
    print_status "Waiting for job ID maintenance to complete..."
    local timeout=300  # 5 minutes timeout
    local elapsed=0
    
    while screen -list | grep -q "jobid_maintain_session"; do
        sleep 5
        elapsed=$((elapsed + 5))
        
        if [ $elapsed -ge $timeout ]; then
            print_warning "Job ID maintenance taking longer than expected (${timeout}s)"
            print_status "Continuing anyway..."
            break
        fi
        
        if [ $((elapsed % 30)) -eq 0 ]; then
            print_status "Still waiting... (${elapsed}s elapsed)"
        fi
    done
    
    print_success "Job ID maintenance completed"
    return 0
}

# Function to run main extraction scripts in parallel
run_extraction_scripts() {
    print_status "Starting $NUM_PARALLEL_INSTANCES parallel extraction instances..."
    
    for i in $(seq 1 $NUM_PARALLEL_INSTANCES); do
        session_name="job_extraction_$i"
        print_status "Starting extraction instance $i in session: $session_name"
        
        # Create screen session for each instance
        screen -dmS "$session_name" bash -c "
            echo 'Starting job extraction instance $i...';
            python '$MAIN_SCRIPT_PATH' --instance $i;
            echo 'Instance $i completed. Press any key to exit...';
            exec bash
        "
        
        if [ $? -ne 0 ]; then
            print_error "Failed to start extraction instance $i"
            return 1
        fi
        
        # Small delay between starting instances
        sleep 2
    done
    
    print_success "All $NUM_PARALLEL_INSTANCES extraction instances started"
    return 0
}

# Function to show running sessions
show_sessions() {
    print_status "Active screen sessions:"
    screen -ls | grep -E 'jobid_maintain_session|job_extraction_' || echo "  No active job extraction sessions"
}

# Function to monitor extraction progress
monitor_progress() {
    print_status "Monitoring extraction progress..."
    print_status "You can attach to any session with: screen -r <session_name>"
    print_status "Available sessions:"
    show_sessions
    
    print_status "To view logs in real-time, use:"
    echo "  screen -r job_extraction_1  # Attach to instance 1"
    echo "  screen -r job_extraction_2  # Attach to instance 2"
    echo "  ... etc"
    
    print_status "To detach from a session: Ctrl+A, then D"
    print_status "To list all sessions: screen -ls"
}

# Function to deactivate virtual environment
deactivate_venv() {
    print_status "Deactivating virtual environment..."
    deactivate 2>/dev/null
    print_success "Virtual environment deactivated"
}

# Main execution
main() {
    print_status "Starting Job Extraction System..."
    print_status "=========================================="
    
    # Pre-flight checks
    if ! check_venv; then
        exit 1
    fi
    
    if ! check_scripts; then
        exit 1
    fi
    
    # Activate virtual environment
    if ! activate_venv; then
        exit 1
    fi
    
    # Clean up old sessions
    cleanup_screens
    
    # Run job ID maintenance
    if ! run_jobid_maintenance; then
        print_error "Job ID maintenance failed"
        deactivate_venv
        exit 1
    fi
    
    # Run extraction scripts
    if ! run_extraction_scripts; then
        print_error "Failed to start extraction scripts"
        deactivate_venv
        exit 1
    fi
    
    # Show monitoring information
    monitor_progress
    
    print_success "Job extraction system started successfully!"
    print_status "=========================================="
    
    # Deactivate virtual environment
    deactivate_venv
    
    print_success "Setup complete. All processes are running in screen sessions."
}

# Handle script interruption
trap 'print_warning "Script interrupted. Cleaning up..."; deactivate_venv 2>/dev/null; exit 130' INT TERM

# Run main function
main "$@"