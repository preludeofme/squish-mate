# Squish-Mate Project Split Plan

## Overview
This document outlines the plan to split the squish-mate project into separate repositories while maintaining the open source nature of the project. The main goal is to create a core behavioral library that can be used across platforms (desktop, web, mobile) while maintaining platform-specific implementations.

## Repository Structure

### 1. Core Behavioral Library
**Repository**: `preludeofme/squish-mate-core`
**Purpose**: Contains all core behavioral logic that can be reused across platforms

### 2. Platform-Specific Implementations
**Repository**: `preludeofme/squish-mate-desktop`
**Repository**: `preludeofme/squish-mate-android` 
**Repository**: `preludeofme/squish-mate-web`
**Purpose**: Platform-specific implementation using the core library

## Core Library Contents (squish-mate-core)

### Core Modules
- `pet_engine.py` - Main deterministic behavior engine
- `pet_brain.py` - LLM integration and safety validation
- `pet_memory.py` - Memory system and relationship management
- `pet_library.py` - Knowledge base and behavior templates
- `llm_providers.py` - Various LLM interface adapters
- `pet_performance.py` - Performance metrics and optimization
- `pet_state.py` - State machine and recovery

### Core Interfaces
- `behavior_interface.py` - Common behavior interface 
- `memory_interface.py` - Memory access patterns
- `input_interface.py` - Input/output abstraction
- `output_interface.py` - Output formats and rendering
- `llm_interface.py` - LLM interaction patterns

## Desktop Implementation (squish-mate-desktop)

### Desktop-Specific Components
- `desktop_pet.py` - Main desktop entry point 
- `pet_renderer.py` - Qt-based rendering 
- `pet_window.py` - Desktop window management
- `activity_monitor.py` - Desktop activity monitoring
- `screen_reader.py` - Screen capture for visual input

### Dependencies
- PyQt6 for GUI rendering
- PySide6 for GUI components
- psutil for system monitoring
- pynput for mouse/keyboard activity
- requests for LLM connectivity

## Android Implementation (squish-mate-android)

### Core Android Components
- `android_pet_renderer.java` - Android rendering engine
- `android_activity_monitor.java` - Android activity monitoring
- `android_input_adapter.java` - Android-specific input handling
- `android_output_adapter.java` - Android output format

### Mobile-Specific Features
- Floating window system (Android's SystemAlertWindow)
- Touch interaction handling
- Battery optimization
- Android permissions integration

## Architectural Changes

### 1. Component Abstraction
```python
# Core interface example
class PetBehaviorInterface:
    def process_activity(self, activity_data):
        raise NotImplementedError
        
    def get_response(self, context, activity):
        raise NotImplementedError
        
    def update_state(self, new_state):
        raise NotImplementedError
```

### 2. Dependency Injection
- Replace direct imports with dependency injection
- Use factory patterns for creating platform-specific components
- Implement plugin architecture for easy extension

### 3. Cross-Platform Interface
```python
# Example of cross-platform interface
class CrossPlatformInterface:
    def __init__(self, platform_type):
        self.platform = platform_type
        self._setup_interfaces()
        
    def _setup_interfaces(self):
        if self.platform == "desktop":
            self.interface = DesktopInterface()
        elif self.platform == "mobile":
            self.interface = MobileInterface()
```

## Development Workflow

### 1. Core Library Development
1. Develop core behavioral logic without platform-specific code
2. Create comprehensive unit tests for core components
3. Establish clear APIs and interfaces

### 2. Platform-Specific Development
1. Use core library as dependency in platform apps
2. Implement platform-specific UI components
3. Apply platform-specific UI and design patterns

### 3. Integration Testing
1. Test core behavior across different platform implementations
2. Verify that core features work as expected
3. Validate that platform-specific features work as expected

## Code Structure

### Before (Single Repository)
```
squish-mate/
├── core/                 # Core components
├── ui/                   # UI components
├── monitors/             # Activity monitoring
├── desktop_pet.py        # Main entry point
├── run_pet.py
└── package.json
```

### After (Split Repositories)
```
squish-mate-core/
├── pet_engine.py
├── pet_brain.py
├── interfaces/
│   ├── behavior_interface.py
│   ├── memory_interface.py
│   └── llm_interface.py
└── utils/
    └── common_functions.py

squish-mate-desktop/
├── desktop_pet.py
├── desktop_ui/
│   ├── pet_window.py
│   ├── pet_renderer.py
│   └── pet_renderer.py
└── desktop_monitor.py

squish-mate-android/
├── android_pet.py
├── android_ui/
│   ├── android_renderer.java
│   └── android_renderer.java
└── android_monitor.py
```

## Implementation Steps

### Phase 1: Core Library Creation
1. Extract core behavioral logic into `squish-mate-core`
2. Establish clear, well-defined interfaces
3. Create comprehensive test suite for core functionality
4. Package core as standalone Python library

### Phase 2: Desktop Implementation
1. Use core library as dependency
2. Implement desktop-specific UI components
3. Add desktop-specific monitoring
4. Integrate with existing desktop workflow

### Phase 3: Mobile Implementation
1. Refactor core interfaces for mobile compatibility
2. Implement mobile-specific UI with Android features
3. Integrate mobile activity monitoring
4. Add optimization for mobile resources

### Phase 4: Integration and Testing
1. Verify all implementations use core consistently
2. Test cross-platform behavior consistency
3. Perform full regression testing
4. Document platform-specific features

## Benefits of Split

1. **Maintainability**: Core logic remains unchanged between platforms
2. **Reusability**: Core functionality can be used for web, mobile, etc.
3. **Specialization**: Platform-specific optimizations can be applied
4. **Modularity**: Easier to extend for new platforms
5. **Testing**: Core functionality can be tested with different platform inputs

## Risk Mitigation

1. **Breaking Changes**: Maintain backward compatibility in interfaces
2. **Testing Complexity**: Create platform-specific testing environments
3. **Maintenance Overhead**: Use CI/CD pipelines for automated testing
4. **Documentation**: Update documentation for each platform-specific implementation

This split preserves the open source nature of the project while making it more extensible and maintaining the quality of core functionality across different platforms.