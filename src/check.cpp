// Independent endpoint validation and replay: no policy or summary routines.
#include "coopsbr/solver.hpp"
#include <algorithm>
#include <fstream>
#include <iostream>
#include <stdexcept>
int main(int argc,char** argv) {
    try {
        if(argc!=3) throw std::runtime_error("Usage: coopsbr-check INPUT TRACE");
        auto p=coopsbr::read_input(argv[1]);
        std::ifstream f(argv[2]);
        std::string magic,extra;
        long long n=0,count=0;
        if(!(f>>magic>>n>>count) || magic!="COOPSBR_TRACE_V1" || n!=static_cast<long long>(p.size()) || count<0 || count>n+1)
            throw std::runtime_error("Invalid trace header");
        for(long long i=0;i<count;++i) {
            long long l,r;
            if(!(f>>l>>r) || l<0 || l>=r || r>=n) throw std::runtime_error("Invalid trace reversal");
            std::reverse(p.begin()+l,p.begin()+r+1);
        }
        if(f>>extra) throw std::runtime_error("Unexpected trailing trace data");
        for(std::size_t i=0;i<p.size();++i) if(p[i]!=static_cast<int>(i)+1) throw std::runtime_error("Replay did not sort the input");
        std::cout<<"{\"verified\":true,\"n\":"<<n<<",\"reversals\":"<<count<<"}\n";
    } catch(const std::exception& e) { std::cerr<<e.what()<<'\n'; return 1; }
}
