#include "coopsbr/solver.hpp"
#include <algorithm>
#include <iostream>
#include <numeric>
#include <random>
#include <cmath>
#include <stdexcept>
using namespace coopsbr;
static void test(const std::vector<int>& p,int& tested,bool all) {
    Options seq;seq.debug=true;auto expected=solve_seq(p,seq);
    for(const auto& coord:{"launches","cooperative","cooperative-replicated","cooperative-fused-full","cooperative-fused-changed","graph"}) for(const auto& update:{"full","incremental"})
    for(const auto& reduction:{"summary","scalar"})
    for(const auto& candidate: all ? std::vector<std::string>{"local","full","materialized"} : std::vector<std::string>{"local"}) {
        Options o;o.mode="gpu-inc";o.coordination=coord;o.update=update;o.candidate=candidate;o.reduction=reduction;o.debug=true;
        o.threads=all?64:128;auto r=solve_gpu(p,o);
        if(r.sorted!=expected.sorted || r.trace.size()!=expected.trace.size()) throw std::runtime_error("GPU output differs from SEQ");
        for(std::size_t i=0;i<r.trace.size();++i)
            if(r.trace[i].left!=expected.trace[i].left || r.trace[i].right!=expected.trace[i].right) throw std::runtime_error("GPU trace differs from SEQ");
        if(std::string(coord)=="cooperative-replicated" &&
           std::string(candidate)!="materialized" && r.barriers!=4*r.trace.size()+2)
            throw std::runtime_error("Unexpected replicated-choice barrier count");
        if(std::string(coord).find("cooperative-fused-")==0 &&
           std::string(candidate)!="materialized" && r.barriers!=3*r.trace.size()+2)
            throw std::runtime_error("Unexpected fused-update barrier count");
        if(std::string(coord)=="graph") {
            if(r.graph_launches!=1 || r.graph_nodes!=(std::string(candidate)=="materialized"?10:9) ||
               r.launches!=3+(std::string(candidate)=="materialized"?6:5)*r.trace.size() ||
               r.barriers!=0 || r.graph_setup_ms<=0 || r.graph_teardown_ms<0 ||
               r.end_to_end_ms<r.sort_ms+r.graph_setup_ms+r.graph_teardown_ms)
                throw std::runtime_error("Invalid graph execution/timing accounting");
        }
        ++tested;
    }
}
int main(int argc,char** argv) {
    try {
        int limit=argc==2?std::stoi(argv[1]):5;
        if(limit<1 || limit>7) throw std::runtime_error("GPU exhaustive limit must be 1..7");
        int tested=0;
        for(int n=1;n<=limit;++n) {
            std::vector<int> p(n);std::iota(p.begin(),p.end(),1);
            do {test(p,tested,false);} while(std::next_permutation(p.begin(),p.end()));
        }
        test({3,6,5,2,1,4},tested,true);
        std::mt19937 rng(42);
        for(int n:{31,32,33,127,128,129,255,256,257,511,512,513,1024}) {
            std::vector<int> p(n);std::iota(p.begin(),p.end(),1);test(p,tested,true);
            std::reverse(p.begin(),p.end());test(p,tested,true);
            std::shuffle(p.begin(),p.end(),rng);test(p,tested,true);
        }
        std::vector<int> probe(513);std::iota(probe.begin(),probe.end(),1);std::shuffle(probe.begin(),probe.end(),rng);
        Options reference;auto target=solve_seq(probe,reference);
        for(const auto& coord:{"cooperative","cooperative-replicated","cooperative-fused-full","cooperative-fused-changed","graph"})
        for(const auto& reduction:{"summary","scalar"})
        for(int threads:{32,128,256}) for(int blocks:{1,2,8}) {
            Options o;o.mode="gpu-inc";o.update="incremental";o.coordination=coord;o.threads=threads;o.blocks=blocks;o.reduction=reduction;o.debug=true;
            auto value=solve_gpu(probe,o);
            if(value.trace.size()!=target.trace.size()) throw std::runtime_error("Grid-sweep trace mismatch");
            for(std::size_t i=0;i<value.trace.size();++i)
                if(value.trace[i].left!=target.trace[i].left || value.trace[i].right!=target.trace[i].right) throw std::runtime_error("Grid-sweep endpoint mismatch");
            ++tested;
        }
        for(const auto& reduction:{"summary","scalar"})
        for(const auto& coord:{"launches","cooperative","cooperative-replicated"}) {
            Options o;o.mode="gpu-inc";o.update="incremental";o.coordination=coord;o.reduction=reduction;o.instrument=true;
            auto value=solve_gpu(probe,o);
            if(value.trace.size()!=target.trace.size()) throw std::runtime_error("Instrumented trace mismatch");
            for(std::size_t i=0;i<value.trace.size();++i)
                if(value.trace[i].left!=target.trace[i].left || value.trace[i].right!=target.trace[i].right) throw std::runtime_error("Instrumented endpoint mismatch");
            double total=0;for(double t:value.phase_ms) { if(t<0 || !std::isfinite(t))throw std::runtime_error("Invalid phase time");total+=t; }
            if(total<=0 || total>value.sort_ms*1.1) throw std::runtime_error("Phase clock does not match host-time scale");
            ++tested;
        }
        auto updates=benchmark_updates(probe,target.trace,6,1);
        if(updates.size()!=12) throw std::runtime_error("Missing update benchmark rows");
        std::cout<<"PASS GPU configurations="<<tested<<'\n';
    } catch(const std::exception& e) {std::cerr<<e.what()<<'\n';return 1;}
}
