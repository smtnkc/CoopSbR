#include "coopsbr/solver.hpp"
#include <chrono>
#include <iomanip>
#include <iostream>
#include <stdexcept>
#include <sstream>
static std::string quote(const std::string& s) {
    std::ostringstream out;out<<'"';
    for(unsigned char c:s) {
        if(c=='"' || c=='\\')out<<'\\'<<c;
        else if(c<32)out<<"\\u"<<std::hex<<std::setw(4)<<std::setfill('0')<<int(c)<<std::dec;
        else out<<c;
    }
    out<<'"';return out.str();
}
int main(int argc,char** argv) {
    try {
        coopsbr::Options o;
        std::string input,trace;
        int warmups=0,repetitions=1,offset=0;
        for(int i=1;i<argc;++i) {
            std::string a=argv[i];
            if(a=="--instrument") { o.instrument=true; continue; }
            if(a=="--debug-state") { o.debug=true; continue; }
            if(i+1>=argc) throw std::runtime_error("Missing option value");
            std::string v=argv[++i];
            if(a=="--warmups") warmups=std::stoi(v);
            else if(a=="--repetitions") repetitions=std::stoi(v);
            else if(a=="--sample-offset") offset=std::stoi(v);
            else if(a=="--input") input=v;
            else if(a=="--trace") trace=v;
            else if(a=="--mode") o.mode=v;
            else if(a=="--update") o.update=v;
            else if(a=="--coord") o.coordination=v;
            else if(a=="--candidate") o.candidate=v;
            else if(a=="--reduction") o.reduction=v;
            else if(a=="--threads") o.threads=std::stoi(v);
            else if(a=="--blocks") o.blocks=std::stoi(v);
            else throw std::runtime_error("Unknown option: "+a);
        }
        if(input.empty() || trace.empty()) throw std::runtime_error("Required: --input FILE --trace FILE --mode seq|gpu-full|gpu-inc");
        if(o.mode!="seq" && o.mode!="gpu-full" && o.mode!="gpu-inc") throw std::runtime_error("Invalid mode");
        if(o.update.empty()) o.update=o.mode=="gpu-full" ? "full" : "incremental";
        if(o.coordination.empty()) o.coordination=o.mode=="gpu-full" ? "launches" : "cooperative";
        if(o.update!="full" && o.update!="incremental") throw std::runtime_error("Invalid update mode");
        if(o.coordination!="launches" && o.coordination!="cooperative" && o.coordination!="cooperative-replicated" &&
           o.coordination!="cooperative-fused-full" && o.coordination!="cooperative-fused-changed" &&
           o.coordination!="graph") throw std::runtime_error("Invalid coordination mode");
        if(o.candidate!="local" && o.candidate!="full" && o.candidate!="materialized") throw std::runtime_error("Invalid candidate mode");
        if(o.reduction!="summary" && o.reduction!="scalar") throw std::runtime_error("Invalid reduction mode");
        if(o.mode=="seq" && o.reduction!="summary") throw std::runtime_error("Scalar reduction is GPU-only");
        if(warmups<0 || warmups>10 || repetitions<1 || repetitions>100 || offset<0) throw std::runtime_error("Invalid repetition counts");
        if(o.mode=="seq" && o.instrument) throw std::runtime_error("Phase instrumentation is GPU-only");
        if(o.coordination=="graph" && o.instrument) throw std::runtime_error("Graph phase instrumentation is not supported");
        auto p=coopsbr::read_input(input);
        for(int iteration=-warmups;iteration<repetitions;++iteration) {
        const auto call_start = std::chrono::steady_clock::now();
        coopsbr::Result r;
        if(o.mode=="seq") r=coopsbr::solve_seq(p,o);
#ifdef COOPSBR_HAS_CUDA
        else r=coopsbr::solve_gpu(p,o);
#else
        else throw std::runtime_error("This executable was built without CUDA");
#endif
        const auto call_end = std::chrono::steady_clock::now();
        const auto wall_ms = std::chrono::duration<double, std::milli>(call_end - call_start).count();
        for(std::size_t i=0;i<r.sorted.size();++i)
            if(r.sorted[i]!=static_cast<int>(i)+1) throw std::runtime_error("Solver did not return the identity");
        std::string trace_path=trace;
        if(warmups || repetitions>1 || offset) trace_path+=iteration<0 ? ".warmup-"+std::to_string(iteration+warmups) : ".sample-"+std::to_string(offset+iteration);
        coopsbr::write_trace(trace_path,static_cast<int>(p.size()),r.trace);
        std::cout<<std::setprecision(12)<<"{\"schema\":1,\"policy\":\"extreme-strip-v1\",\"mode\":\""<<o.mode
          <<"\",\"update\":\""<<(o.mode=="seq"?"full":o.update)<<"\",\"coordination\":\""<<(o.mode=="seq"?"sequential":o.coordination)<<"\",\"candidate\":\""<<(o.mode=="seq"?"virtual-short-circuit":o.candidate)
          <<"\",\"reduction\":\""<<(o.mode=="seq"?"sequential":o.reduction)
          <<"\",\"debug\":"<<(o.debug?"true":"false")<<",\"n\":"<<p.size()<<",\"reversals\":"<<r.trace.size()
          <<",\"initial_breakpoints\":"<<r.initial_breakpoints<<",\"sort_ms\":"<<r.sort_ms<<",\"end_to_end_ms\":"<<r.end_to_end_ms
          <<",\"paired_wall_ms\":"<<wall_ms
          <<",\"context_ms\":"<<r.context_ms<<",\"allocation_ms\":"<<r.allocation_ms<<",\"h2d_ms\":"<<r.h2d_ms<<",\"d2h_ms\":"<<r.d2h_ms
          <<",\"graph_setup_ms\":"<<r.graph_setup_ms<<",\"graph_teardown_ms\":"<<r.graph_teardown_ms
          <<",\"graph_launches\":"<<r.graph_launches<<",\"graph_nodes\":"<<r.graph_nodes
          <<",\"allocated_bytes\":"<<r.allocated_bytes<<",\"kernel_launches\":"<<r.launches<<",\"grid_barriers\":"<<r.barriers
          <<",\"updated_elements\":"<<r.updated_elements<<",\"candidate_elements\":"<<r.candidate_elements
          <<",\"summary_elements\":"<<r.summary_elements<<",\"candidate_copy_elements\":"<<r.candidate_copy_elements
          <<",\"instrumented\":"<<(o.instrument?"true":"false")
          <<",\"phase_ms\":["<<r.phase_ms[0]<<','<<r.phase_ms[1]<<','<<r.phase_ms[2]<<','<<r.phase_ms[3]<<','<<r.phase_ms[4]<<','<<r.phase_ms[5]<<']'
          <<",\"blocks\":"<<r.blocks<<",\"threads\":"<<r.threads
          <<",\"warmup\":"<<(iteration<0?"true":"false")<<",\"sample\":"<<(iteration<0?iteration+warmups:iteration+offset)
          <<",\"trace_path\":"<<quote(trace_path)<<"}\n"<<std::flush;
        }
    } catch(const std::exception& e) { std::cerr<<e.what()<<'\n'; return 1; }
}
