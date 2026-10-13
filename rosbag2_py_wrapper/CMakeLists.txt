# Modified 2026 by Eelis Peltola: C++17, CMake 3.20, ROS2 Lyrical -supported target linking.

cmake_minimum_required(VERSION 3.20)
project(rosbag2_py_wrapper)

### Compile options
if(NOT CMAKE_CXX_STANDARD)
  set(CMAKE_CXX_STANDARD 17)
  set(CMAKE_CXX_STANDARD_REQUIRED ON)
  set(CMAKE_CXX_EXTENSIONS OFF)
endif()
if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic -Werror)
endif()

find_package(ament_cmake_auto REQUIRED)
find_package(Python3 REQUIRED COMPONENTS Interpreter Development)

ament_auto_find_build_dependencies()
find_package(pybind11 REQUIRED)

ament_python_install_package(${PROJECT_NAME})

pybind11_add_module(_writer SHARED
  src/rosbag2_py_wrapper/_writer.cpp
)
target_link_libraries(_writer PRIVATE
  rosbag2_cpp::rosbag2_cpp
  rosbag2_storage::rosbag2_storage
)

# Install cython modules as sub-modules of the project
install(
  TARGETS
    _writer
  DESTINATION "${PYTHON_INSTALL_DIR}/${PROJECT_NAME}"
)

if(BUILD_TESTING)
  find_package(ament_lint_auto REQUIRED)
  ament_lint_auto_find_test_dependencies()
  find_package(ament_cmake_pytest REQUIRED)

endif()

ament_package()
