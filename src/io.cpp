#include "coopsbr/solver.hpp"
#include <fstream>
#include <stdexcept>
namespace coopsbr {
std::vector<int> read_input(const std::string& path) {
    std::ifstream f(path);
    long long n=0;
    if (!(f>>n) || n<1 || n>INT_MAX/4) throw std::runtime_error("Invalid length or unreadable input");
    std::vector<int> p(static_cast<std::size_t>(n));
    std::vector<bool> seen(static_cast<std::size_t>(n)+1,false);
    for (int& v:p) {
        if (!(f>>v) || v<1 || v>n || seen[v]) throw std::runtime_error("Input must be a permutation of 1..n");
        seen[v]=true;
    }
    std::string extra;
    if (f>>extra) throw std::runtime_error("Unexpected trailing input");
    return p;
}
void write_trace(const std::string& path,int n,const std::vector<Reversal>& trace) {
    std::ofstream f(path);
    if (!f) throw std::runtime_error("Cannot open trace output");
    f<<"COOPSBR_TRACE_V1 "<<n<<' '<<trace.size()<<'\n';
    for (auto r:trace) f<<r.left<<' '<<r.right<<'\n';
    if (!f) throw std::runtime_error("Trace write failed");
}
}
