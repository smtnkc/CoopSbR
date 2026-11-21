#include "coopsbr/solver.hpp"
#include <fstream>
#include <iomanip>
#include <iostream>
#include <stdexcept>
int main(int argc,char** argv) {
    try {
        std::string input,trace,output;int states=24,repetitions=3;
        for(int i=1;i<argc;++i) {
            if(i+1>=argc) throw std::runtime_error("Missing option value");
            std::string key=argv[i],value=argv[++i];
            if(key=="--input") input=value;
            else if(key=="--trace") trace=value;
            else if(key=="--output") output=value;
            else if(key=="--max-states") states=std::stoi(value);
            else if(key=="--repetitions") repetitions=std::stoi(value);
            else throw std::runtime_error("Unknown option");
        }
        if(input.empty() || trace.empty() || output.empty()) throw std::runtime_error("Required: --input FILE --trace FILE --output CSV");
        auto p=coopsbr::read_input(input);
        std::ifstream f(trace);std::string magic,extra;long long n,count;
        if(!(f>>magic>>n>>count) || magic!="COOPSBR_TRACE_V1" || n!=static_cast<long long>(p.size()) || count<0 || count>n+1)
            throw std::runtime_error("Invalid source trace header");
        std::vector<coopsbr::Reversal> reversals;
        for(long long i=0;i<count;++i) {
            int l,r;if(!(f>>l>>r)||l<0||l>=r||r>=n) throw std::runtime_error("Invalid source endpoints");
            reversals.push_back({l,r});
        }
        if(f>>extra) throw std::runtime_error("Trailing trace data");
        auto rows=coopsbr::benchmark_updates(p,reversals,states,repetitions);
        std::ofstream out(output);
        if(!out) throw std::runtime_error("Cannot open CSV output");
        out<<"step,n,length,strips,summary_elements,sample,update,reversal_device_ms,metadata_device_ms,update_wall_ms,verified\n"<<std::setprecision(12);
        for(auto r:rows) out<<r.step<<','<<n<<','<<r.length<<','<<r.strips<<','<<r.summary_elements<<','<<r.sample<<','
            <<(r.incremental?"incremental":"full")<<','<<r.reversal_ms<<','<<r.metadata_ms<<','<<r.wall_ms<<",true\n";
        if(!out) throw std::runtime_error("CSV write failed");
        std::cout<<"{\"verified\":true,\"measurements\":"<<rows.size()<<"}\n";
    } catch(const std::exception& e) {std::cerr<<e.what()<<'\n';return 1;}
}
