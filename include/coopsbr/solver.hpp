#pragma once
#include "policy.hpp"
#include <cstdint>
#include <array>
#include <string>
#include <vector>
namespace coopsbr {
struct Options {
    std::string mode="seq", update="", coordination="", candidate="local", reduction="summary";
    int threads=128, blocks=0;
    bool debug=false, instrument=false;
};
struct Result {
    std::array<double,6> phase_ms{};
    std::vector<int> sorted;
    std::vector<Reversal> trace; // Zero-based, inclusive endpoints in the user's n-element input.
    double context_ms=0, sort_ms=0, end_to_end_ms=0, allocation_ms=0, h2d_ms=0, d2h_ms=0;
    double graph_setup_ms=0, graph_teardown_ms=0;
    std::uint64_t graph_launches=0, graph_nodes=0;
    std::uint64_t allocated_bytes=0, launches=0, barriers=0, updated_elements=0, candidate_elements=0, summary_elements=0, candidate_copy_elements=0;
    int initial_breakpoints=0, blocks=0, threads=1;
};
std::vector<int> read_input(const std::string& path);
void write_trace(const std::string& path, int n, const std::vector<Reversal>& trace);
Result solve_seq(const std::vector<int>& input, const Options& options);
#ifdef COOPSBR_HAS_CUDA
struct UpdateMeasurement {
    int step=0, length=0, strips=0, summary_elements=0, sample=0;
    bool incremental=false;
    double reversal_ms=0, metadata_ms=0, wall_ms=0;
};
std::vector<UpdateMeasurement> benchmark_updates(const std::vector<int>& input,
    const std::vector<Reversal>& trace, int max_states, int repetitions);
Result solve_gpu(const std::vector<int>& input, const Options& options);
#endif
}
